from flask import Flask, request, jsonify
from ortools.sat.python import cp_model
from datetime import datetime

app = Flask(__name__)

def in_range(date_str, start, end):
    d = datetime.fromisoformat(date_str).date()
    return datetime.fromisoformat(start).date() <= d <= datetime.fromisoformat(end).date()

@app.route("/gerar", methods=["POST"])
def gerar():
    data = request.json

    medicos_in = data["medicos"]  # [{nome, podeMaio}]
    nomes = [m["nome"] for m in medicos_in]
    pode_maio = {m["nome"]: bool(m.get("podeMaio", True)) for m in medicos_in}

    indis = data["indisponibilidades"]  # [{nome, inicio, fim}]
    datas = data["datas"]               # ["YYYY-MM-DD", ...]
    regras = data.get("regras", {})

    nS = len(datas)

    model = cp_model.CpModel()

    # x[m,s] = 1 se médico m no slot s
    x = {(m,s): model.NewBoolVar(f"x_{m}_{s}") for m in nomes for s in range(nS)}

    # 2 médicos por slot
    for s in range(nS):
        model.Add(sum(x[(m,s)] for m in nomes) == 2)

    # indisponibilidades + regras de mês
    for m in nomes:
        for s in range(nS):
            d = datas[s]

            # Maria Lúcia fora de maio (pode_maio = False)
            if d.startswith("2026-05") and not pode_maio.get(m, True):
                model.Add(x[(m,s)] == 0)

            # Sávio só em maio
            if m.lower().startswith("savio") and not d.startswith("2026-05"):
                model.Add(x[(m,s)] == 0)

            # indisponibilidades por intervalo
            for r in indis:
                if r["nome"] == m and in_range(d, r["inicio"], r["fim"]):
                    model.Add(x[(m,s)] == 0)

    # Maio fixo (5 primeiros sábados)
    maio_fixos = [
        ("Victor","Savio"),
        ("Savio","Carolina"),
        ("Mayra","Silvana"),
        ("Victor","Mayra"),
        ("Carolina","Victor"),
    ]
    for s in range(min(5, nS)):
        m1, m2 = maio_fixos[s]
        if m1 in nomes: model.Add(x[(m1,s)] == 1)
        if m2 in nomes: model.Add(x[(m2,s)] == 1)

    # Evitar Carolina + Silvana (penalidade)
    penalties = []
    if regras.get("cs", True):
        for s in range(nS):
            if "Carolina" in nomes and "Silvana" in nomes:
                both = model.NewBoolVar(f"cs_{s}")
                # both = 1 se ambos no slot
                model.Add(x[("Carolina",s)] + x[("Silvana",s)] == 2).OnlyEnforceIf(both)
                model.Add(x[("Carolina",s)] + x[("Silvana",s)] != 2).OnlyEnforceIf(both.Not())
                penalties.append(both)

    # Victor 14/14 a partir do primeiro sábado >= 2026-06-13
    if regras.get("victor", True) and "Victor" in nomes:
        # encontre o índice do primeiro sábado >= 2026-06-13
        start_idx = None
        for i, d in enumerate(datas):
            if d >= "2026-06-13":
                start_idx = i
                break
        if start_idx is not None:
            # Força padrão alternado: Victor nos índices start_idx, start_idx+2, ...
            for s in range(start_idx, nS):
                if (s - start_idx) % 2 == 0:
                    model.Add(x[("Victor",s)] == 1)
                else:
                    model.Add(x[("Victor",s)] == 0)

    # Balanceamento: minimizar max - min
    cargas = []
    for m in nomes:
        cargas.append(sum(x[(m,s)] for s in range(nS)))

    max_c = model.NewIntVar(0, 100, "max_c")
    min_c = model.NewIntVar(0, 100, "min_c")
    model.AddMaxEquality(max_c, cargas)
    model.AddMinEquality(min_c, cargas)

    obj_terms = []
    obj_terms.append(max_c - min_c)

    # penalidade CS (peso 5)
    if penalties:
        obj_terms.append(5 * sum(penalties))

    model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20
    solver.parameters.num_search_workers = 8

    res = solver.Solve(model)

    if res not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return jsonify({"error":"Sem solução viável com as regras atuais"}), 400

    saida = []
    for s in range(nS):
        dupla = [m for m in nomes if solver.Value(x[(m,s)]) == 1]
        saida.append({
            "data": datas[s],
            "m1": dupla[0] if len(dupla)>0 else "",
            "m2": dupla[1] if len(dupla)>1 else ""
        })

    return jsonify(saida)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

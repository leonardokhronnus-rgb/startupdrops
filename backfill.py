#!/usr/bin/env python3
"""
backfill.py — Traduz para pt-BR os artigos internacionais que ja estao em
data/news.json em ingles (os que nunca passaram pela IA).

Roda UMA vez. Reescreve title + summary + whyMatters no lugar e marca
summaryMethod = "ia". Faz backup antes. Nao mexe em artigos BR nem nos que
ja foram traduzidos.

Uso (dentro da pasta do repo):
    ANTHROPIC_API_KEY=sua-chave  python backfill.py

Opcional:
    python backfill.py --dry-run     # mostra o que faria, sem salvar
    python backfill.py --limit 20    # traduz so os 20 primeiros (pra testar)
"""

import os, sys, json, re, time, shutil, argparse

DATA_PATH = "data/news.json"
MODEL = "claude-haiku-4-5-20251001"
INTL_COUNTRIES = {"US", "EU", "CN", "IN"}

# Sinais de que o titulo ainda esta em ingles (mesmo padrao do site).
ENGLISH_RESIDUE = re.compile(
    r"\b(the|with|from|for|and|to|at|of|in|on|by|its|their|new|raises?|raised|"
    r"funding|round|seed|series|valuation|billion|million|backed|acquires?|"
    r"acquisition|merger|deal|launch(?:es|ed)?|build|develop|expands?|company|"
    r"market|growth|announced|shares|surge|host|money|fund)\b",
    re.I,
)


def needs_translation(a):
    if a.get("country") not in INTL_COUNTRIES:
        return False
    if a.get("summaryMethod") == "ia":
        return False
    title = a.get("title", "") or ""
    original = a.get("originalTitle", "") or ""
    # ainda cru: titulo == original OU titulo tem residuo de ingles
    return title == original or bool(ENGLISH_RESIDUE.search(title))


def get_client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("ERRO: defina ANTHROPIC_API_KEY no ambiente.", file=sys.stderr)
        sys.exit(1)
    import anthropic
    return anthropic.Anthropic(api_key=key)


def build_prompt(title, source_text, country):
    lang_note = (
        "O conteudo pode estar em chines, traduza e interprete para portugues do Brasil.\n"
        if country == "CN" else ""
    )
    return (
        "Voce e editor senior de um portal brasileiro sobre startups e tecnologia global.\n"
        "REGRAS ABSOLUTAS:\n"
        "- Escreva TUDO em portugues do Brasil correto e fluente. ZERO palavras em ingles no texto final.\n"
        "- Se o original estiver em ingles ou chines, TRADUZA completamente. Nao misture idiomas.\n"
        "- O TITULO deve ser especifico: diga O QUE aconteceu, com QUEM e POR QUE importa. "
        "NUNCA use 'X avanca em Y' ou 'X anuncia Z'.\n"
        "- Se o titulo original nao trouxer um nome de empresa claro, use o assunto real da noticia, "
        "nunca um fragmento solto da manchete.\n"
        "- NAO invente dados. NAO inclua legendas de foto ou creditos de imagem.\n\n"
        f"{lang_note}"
        "Com base no titulo e texto abaixo, gere:\n"
        "TITULO: [titulo especifico em pt-BR, max 90 chars, sem verbos vagos]\n"
        "O QUE ACONTECEU: [2 frases objetivas em pt-BR com fatos, numeros e nomes]\n"
        "POR QUE IMPORTA: [1 frase em pt-BR sobre relevancia para founders/investidores]\n\n"
        f"Titulo original: {title}\n"
        f"Texto: {source_text}"
    )


def translate(client, a):
    title = a.get("originalTitle") or a.get("title") or ""
    source_text = (a.get("summary") or "")[:1500]
    prompt = build_prompt(title, source_text, a.get("country", "US"))
    resp = client.messages.create(
        model=MODEL, max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    out = " ".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    new_title, what, why = None, [], None
    for line in out.split("\n"):
        s = line.strip()
        if s.startswith("TITULO:"):
            new_title = s.replace("TITULO:", "").strip()
        elif s.startswith("O QUE ACONTECEU:"):
            what.append(s.replace("O QUE ACONTECEU:", "").strip())
        elif s.startswith("POR QUE IMPORTA:"):
            why = s.replace("POR QUE IMPORTA:", "").strip()
    summary = " ".join(what).strip()
    if not new_title or len(summary) < 20:
        return None
    return {"title": new_title, "summary": summary, "whyMatters": why or ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    with open(DATA_PATH, encoding="utf-8") as f:
        payload = json.load(f)
    arts = payload["articles"]

    targets = [a for a in arts if needs_translation(a)]
    if args.limit:
        targets = targets[: args.limit]
    print(f"{len(targets)} artigos internacionais em ingles para traduzir.\n")

    if args.dry_run:
        for a in targets[:30]:
            print(f"  [{a.get('country')}] {a.get('title','')[:80]}")
        print("\n(dry-run: nada salvo)")
        return

    if not targets:
        print("Nada a fazer. Tudo ja esta em pt-BR.")
        return

    shutil.copy(DATA_PATH, DATA_PATH + ".bak")
    print(f"Backup salvo em {DATA_PATH}.bak\n")

    client = get_client()
    ok = fail = 0
    for i, a in enumerate(targets, 1):
        try:
            res = translate(client, a)
            if res:
                a["title"] = res["title"]
                a["summary"] = res["summary"]
                a["whyMatters"] = res["whyMatters"]
                a["summaryMethod"] = "ia"
                ok += 1
                print(f"  {i}/{len(targets)} OK  -> {res['title'][:70]}")
            else:
                fail += 1
                print(f"  {i}/{len(targets)} pulado (resposta fraca): {a.get('title','')[:60]}")
        except Exception as e:
            fail += 1
            print(f"  {i}/{len(targets)} ERRO ({e}): {a.get('title','')[:60]}")
        time.sleep(0.4)  # respira entre chamadas
        if i % 25 == 0:  # salva parcial a cada 25
            with open(DATA_PATH, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\nPronto. Traduzidos: {ok} | Falhas/pulados: {fail}")
    print("Se algo der errado, restaure com:  mv data/news.json.bak data/news.json")


if __name__ == "__main__":
    main()

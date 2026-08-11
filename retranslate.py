#!/usr/bin/env python3
"""
StartupDrops — Retradutor do acervo (uso único / manual)
--------------------------------------------------------
Percorre data/news.json e RE-traduz com IA os artigos que ainda estão
com título/resumo em inglês (os que foram gerados por 'regra' antes da
IA estar ativa). Preserva artigos em português (BR) e os que já foram
feitos por IA. Reaproveita a função summary_by_ai do collector.py, então
o resultado é idêntico ao da coleta normal.

Uso:
    ANTHROPIC_API_KEY=... python retranslate.py            # traduz tudo que precisa
    ANTHROPIC_API_KEY=... python retranslate.py --limit 50 # traduz no máximo 50 (teste)

Só age se ANTHROPIC_API_KEY estiver presente. Sem a chave, não faz nada.
"""

import os
import re
import sys
import json
import argparse

import collector as C  # reusa summary_by_ai, strip_html, DATA_PATH, MIN_SUMMARY_CHARS


# Detecta resíduo de inglês no texto — mesmo espírito do hasEnglishResidue do front.
_EN = re.compile(
    r"\b(the|with|from|for|and|company|companies|market|growth|announced|"
    r"acquisition|raises|raised|funding|round|seed|series|backed|launches|"
    r"launched|unveils|based|develop|platform|to build|first close|its|"
    r"expand|new|deal|invests|invested)\b",
    re.I,
)


def looks_english(text: str) -> bool:
    return bool(_EN.search(text or ""))


def needs_translation(a: dict) -> bool:
    # Nunca mexe em manual nem em BR (já em português).
    if a.get("isManual"):
        return False
    if a.get("country") == "BR" or a.get("region") == "Brasil":
        return False
    # Já traduzido por IA e sem resíduo de inglês? Deixa quieto.
    title = a.get("title", "")
    summary = a.get("summary", "")
    if a.get("summaryMethod") == "ia" and not looks_english(title) and not looks_english(summary):
        return False
    # Estrangeiro com inglês em título ou resumo -> traduzir.
    return looks_english(title) or looks_english(summary)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="máx. de artigos a traduzir (0 = todos)")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY ausente — nada a fazer.", file=sys.stderr)
        sys.exit(1)

    with open(C.DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    articles = data.get("articles", [])
    todo = [a for a in articles if needs_translation(a)]
    print(f"Acervo: {len(articles)} artigos. Precisam de tradução: {len(todo)}", file=sys.stderr)

    if args.limit and args.limit > 0:
        todo = todo[: args.limit]
        print(f"Limite aplicado: traduzindo {len(todo)} nesta execução.", file=sys.stderr)

    done = 0
    failed = 0
    for a in todo:
        orig_title = a.get("originalTitle") or a.get("title") or ""
        raw = a.get("summary") or ""
        country = a.get("country", "US")
        region = a.get("region", "Internacional")
        try:
            ai_summary, ai_title = C.summary_by_ai(orig_title, raw, region, country)
        except Exception as e:
            print(f"  [erro] {orig_title[:60]} -> {e}", file=sys.stderr)
            ai_summary, ai_title = None, None

        if not ai_summary:
            failed += 1
            continue

        # separa "por que importa" se veio no formato ||WHY||
        clean_summary = ai_summary.strip()
        why = a.get("whyMatters", "")
        if "||WHY||" in clean_summary:
            parts = clean_summary.split("||WHY||", 1)
            clean_summary = parts[0].strip()
            why = parts[1].strip()

        # só aceita se ficou minimamente denso
        if len(clean_summary) < 20:
            failed += 1
            continue

        if ai_title:
            a["title"] = ai_title
        a["summary"] = clean_summary
        a["whyMatters"] = why
        a["summaryMethod"] = "ia"
        done += 1
        if done % 10 == 0:
            print(f"  ... {done} traduzidos", file=sys.stderr)

    with open(C.DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Concluído: {done} traduzidos, {failed} falharam (mantidos como estavam).", file=sys.stderr)


if __name__ == "__main__":
    main()

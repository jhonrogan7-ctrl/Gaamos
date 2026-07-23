def build_fixture(company_slug, branches, menu, routing):
    """Merge Gate-1 menu + Gate-2 routing into the import_menu fixture dict."""
    items = []
    for it in menu.get("items", []):
        rec = dict(it)
        r = routing.get(it["slug"])
        rec["image"] = ({"file": r["file"], "source": r.get("source", "generated"),
                         "origin_url": r.get("origin_url"), "prompt": r.get("prompt")}
                        if r else None)
        items.append(rec)
    return {"company": company_slug, "branches": list(branches),
            "categories": menu.get("categories", []), "items": items}

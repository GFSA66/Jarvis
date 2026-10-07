import json, os, sys

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")


def load():
    try:
        return json.load(open(P))
    except Exception:
        return {"status": {}, "verified": [], "unknowns": [], "lessons": []}


def save(s):
    json.dump(s, open(P, "w"), ensure_ascii=False, indent=1)


def main():
    args = sys.argv[1:]
    if not args or args[0] == "show":
        print(json.dumps(load(), ensure_ascii=False, indent=1))
        return
    if args[0] == "update":
        s = load()
        i = 1
        while i < len(args):
            a = args[i]
            if a == "--verified":
                s["verified"].append(args[i + 1])
                i += 2
            elif a == "--status":
                k, v = args[i + 1].split("=", 1)
                if v == "done":
                    raise SystemExit("use --verified")
                s["status"][k] = v
                i += 2
            elif a == "--unknown":
                s["unknowns"].append(args[i + 1])
                i += 2
            elif a == "--resolved":
                s["unknowns"] = [u for u in s["unknowns"] if u != args[i + 1]]
                i += 2
            elif a == "--lesson":
                s["lessons"].append(args[i + 1])
                s["lessons"] = s["lessons"][-5:]
                i += 2
            else:
                i += 1
        save(s)
        print(json.dumps({
            "status": s["status"],
            "open": s["unknowns"],
            "recent": s["lessons"][-3:],
        }, ensure_ascii=False))


main()

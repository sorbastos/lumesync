import argparse
import json
from dataclasses import asdict
from .config import build, load


def main():
    parser = argparse.ArgumentParser(description="Lume Sync: prévia e sincronização sem interface")
    parser.add_argument("command", choices=["plan", "sync"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    engine = None
    try:
        engine = build(load())
        actions = engine.plan()
        if args.command == "sync":
            engine.apply(actions, notify=lambda text: print(text) if not args.json else None)
            actions = engine.plan()
        if args.json:
            print(json.dumps({"actions": [asdict(a) for a in actions], "notices": engine.provider.notices}, ensure_ascii=False, indent=2))
        else:
            for action in actions:
                print(f"{action.kind:10} {action.path} — {action.reason}")
            for notice in engine.provider.notices: print(notice)
    except Exception as error:
        parser.exit(1, f"Erro: {error}\n")
    finally:
        if engine: engine.state.close()


if __name__ == "__main__": main()

import argparse
from staff_tools.compiler.compile import compile_design
from staff_tools.critic.critic import critic
from staff_tools.eval.eval import run_eval

def main():
    p = argparse.ArgumentParser(prog="staff-tools")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compile", help="compile design -> generated manifests")
    c.add_argument("--design", default="staff-tools/staff_tools/design/staff.yaml")
    c.add_argument("--out", default="staff-tools/generated")

    k = sub.add_parser("critic", help="lint design for risks/missing handoffs")
    k.add_argument("--design", default="staff-tools/staff_tools/design/staff.yaml")

    e = sub.add_parser("eval", help="run compile+critic+basic checks")
    e.add_argument("--design", default="staff-tools/staff_tools/design/staff.yaml")
    e.add_argument("--out", default="staff-tools/generated")

    args = p.parse_args()

    if args.cmd == "compile":
        compile_design(args.design, args.out)
    elif args.cmd == "critic":
        critic(args.design)
    elif args.cmd == "eval":
        run_eval(args.design, args.out)

if __name__ == "__main__":
    main()

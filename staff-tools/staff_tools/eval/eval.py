from staff_tools.compiler.compile import compile_design
from staff_tools.critic.critic import critic

def run_eval(design_path: str, out_dir: str) -> None:
    critic(design_path)
    compile_design(design_path, out_dir)
    print("[eval] OK")

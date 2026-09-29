"""여러 백필을 차례로(같은 rest.lock 을 쓰므로 동시에 못 돌린다). 사용: python run_chain.py "toss_candles.py --targets x.csv" "toss_flows.py --universe" """
import subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
for job in sys.argv[1:]:
    parts = job.split()
    print(f"=== {job}", flush=True)
    subprocess.run([sys.executable, str(HERE / parts[0]), *parts[1:]], check=False)

from pathlib import Path
from process_all import duplicate_analysis, ROOT

if __name__ == "__main__":
    result = duplicate_analysis(ROOT / "09_PROCESSED" / "candidate_master" / "sif_public_data_master.csv")
    print(result)

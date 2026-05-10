import pandas as pd
from datetime import datetime
import os

EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)

def export_to_excel(data: list[dict], prefix: str = "output") -> str:
    filename = f"{prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    path = os.path.join(EXPORT_DIR, filename)

    df = pd.DataFrame(data)
    df.to_excel(path, index=False)

    return path
from pathlib import Path


path = Path("app/relationship_state.py")
text = path.read_text(encoding="utf-8")
old = '("love", "romance", "boyfriend", "girlfriend", "partner", "crush", "lover", "парень", "девуш", "быв", "влюб")'
new = '("love", "romance", "romantic", "boyfriend", "girlfriend", "partner", "crush", "lover", "парень", "девуш", "быв", "влюб")'
if old in text:
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
elif new not in text:
    raise SystemExit("romance role tuple not found")

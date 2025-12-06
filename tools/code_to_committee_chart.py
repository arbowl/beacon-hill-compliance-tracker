from components.committees import get_committees

if __name__ == "__main__":
    committees = sorted(get_committees(
        "https://malegislature.gov", ("Joint", "House", "Senate")
    ), key=lambda c: c.id)
    for c in committees:
        print(f"{c.id}: {c.name}")
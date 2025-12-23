import matplotlib.pyplot as plt
import matplotlib as mpl
import colorsys

# --- Data -------------------------------------------------------

committee_missing_votes = {
    "Joint Committee on the Judiciary": 233,
    "Joint Committee on Revenue": 210,
    "Joint Committee on Municipalities and Regional Government": 164,
    "Joint Committee on Public Health": 153,
    "Joint Committee on Education": 139,
    "Joint Committee on Environment and Natural Resources": 131,
    "Joint Committee on Public Service": 124,
    "Joint Committee on Telecommunications, Utilities and Energy": 101,
    "Joint Committee on Financial Services": 95,
}

# Sort descending
sorted_pairs = sorted(committee_missing_votes.items(), key=lambda x: x[1], reverse=True)
committees = [c for c, v in sorted_pairs]
values = [v for c, v in sorted_pairs]

# --- Style Tweaks ------------------------------------------------

mpl.rcParams["font.family"] = "DejaVu Sans"  # safe on Linux
mpl.rcParams["axes.titlesize"] = 18
mpl.rcParams["axes.labelsize"] = 12
mpl.rcParams["xtick.labelsize"] = 10
mpl.rcParams["ytick.labelsize"] = 10

# Base color (#003366)
base_hex = "#003366"

# Convert hex → RGB → HLS
base_rgb = mpl.colors.to_rgb(base_hex)
h, l, s = colorsys.rgb_to_hls(*base_rgb)

# Generate subtle tonal ramp (slightly lighter for lower-ranked items)
num = len(values)
colors = [colorsys.hls_to_rgb(h, min(1, l + (i * 0.015)), s) for i in range(num)]

plt.figure(figsize=(11, 6.8))

bars = plt.barh(
    committees,
    values,
    color=colors,
    edgecolor="none",
)

# Rounded caps
for bar in bars:
    bar.set_linewidth(0)
    bar.set_capstyle("round")

# Invert y-axis so highest value is top
plt.gca().invert_yaxis()

# Value labels
for i, v in enumerate(values):
    plt.text(
        v + max(values) * 0.01,
        i,
        str(v),
        va="center",
        fontsize=10,
        color="#2d2d2d",
    )

# Axis & grid polish
ax = plt.gca()
for spine in ["top", "right", "left"]:
    ax.spines[spine].set_visible(False)
ax.spines["bottom"].set_color("#bbbbbb")

plt.grid(axis="x", linestyle="--", linewidth=0.6, alpha=0.25)

# Titles
plt.title(
    "Top 10 Legislative Committees by Missing Vote Count",
    pad=25,
    fontweight="bold",
    color="#1a1a1a",
)
plt.xlabel("Missing Votes", color="#333333")

plt.tight_layout()

plt.savefig("top_10_missing_votes_polished.png", dpi=300)
plt.show()

# AI flood detection — false negative review

4 tiles where ground truth says flooded but the AI predicted `flood_damage_detected: false`.

## 0_36_60
- AI reasoning: "The POST-event image is almost entirely covered by thick clouds, obscuring the ground and preventing visual detection of any flood damage." (confidence: low)
- Ground truth: 1 of 163 labelled features flooded (0.6%)

## 0_36_61
- AI reasoning: "The POST-event image is heavily obscured by thick cloud cover, making it impossible to clearly observe the ground and identify any visible flood damage." (confidence: low)
- Ground truth: 15 of 145 labelled features flooded (10.3%)

## 0_40_59
- AI reasoning: "The POST-event image shows green agricultural fields and residential areas with no visible standing water, inundation, or structural flood damage compared to the PRE-event image." (confidence: medium)
- Ground truth: 11 of 85 labelled features flooded (12.9%)

## 0_40_60
- AI reasoning: "The POST-event image is heavily obscured by thick cloud cover, preventing visual confirmation of any ground-level flood damage." (confidence: low)
- Ground truth: 1 of 21 labelled features flooded (4.8%)

## Assessment

Not uniform: 3 of 4 (0_36_60, 0_36_61, 0_40_60) are explained by the model's own reasoning as cloud-obscured imagery, correctly flagged with low confidence — an honest "can't tell" rather than a confident wrong answer, though 0_36_61 (10.3% flooded features) shows cloud cover can mask a non-trivial flood extent. 0_40_59 is different and more concerning: the AI reports clear visibility with no cloud cover mentioned and states confidently (medium) that there's no visible water, while ground truth shows 12.9% of labelled features flooded (11 features) — not a borderline 1-2-feature edge case. Whether that reflects flooding too subtle to see at 512px resolution or a genuine model miss can't be determined from the data alone; it should be treated as a real detection gap, not written off as ambiguous ground truth.

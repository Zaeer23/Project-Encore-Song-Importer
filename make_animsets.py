#!/usr/bin/env python3

import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "42", "media", "AnimSets", "player", "actions")

NODES = [
    ("PE_Guitar_Idle", "guitar", "idle", "PE_GuitarIdle", True, "PETempo", 0.16, 120, "PE_Guitar_Hit"),
    ("PE_Guitar_Hit", "guitar", "hit", "PE_GuitarStrum", True, "PETempo", 0.16, 130, "PE_Guitar_Idle"),

    ("PE_Drums_Idle", "drums", "idle", "Bob_EmoteShiftWeight", True, 0.70, 0.08, 120, "PE_Drums_Hit"),
    ("PE_Drums_Hit", "drums", "hit", "Bob_Attack1Hand01_Hit", False, 2.40, 0.08, 130, "PE_Drums_Idle"),

    ("PE_Vocals_Idle", "vocals", "idle", "PE_SingIdle", True, "PETempo", 0.22, 120, "PE_Vocals_Hit"),
    ("PE_Vocals_Hit", "vocals", "hit", "PE_SingLine", True, "PETempo", 0.22, 130, "PE_Vocals_Idle"),

    ("PE_Harmonica_Idle", "harmonica", "idle", "Bob_EmoteBlowHarmonica_R", True, 0.80, 0.18, 120, "PE_Harmonica_Hit"),
    ("PE_Harmonica_Hit", "harmonica", "hit", "Bob_EmoteBlowHarmonica_R", False, 1.30, 0.18, 130, "PE_Harmonica_Idle"),

    ("PE_Keys_Idle", "keys", "idle", "Bob_EmoteShiftWeight", True, 0.60, 0.08, 120, "PE_Keys_Hit"),
    ("PE_Keys_Hit", "keys", "hit", "Bob_Attack1Hand01_Hit", False, 2.20, 0.08, 130, "PE_Keys_Idle"),
]


def ident(node, index):
    h = 0
    for ch in "%s/%d" % (node, index):
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    hx = "%08x" % h
    return "%s-%s-4%s-8%s-%s%s" % (hx, hx[:4], hx[1:4], hx[2:5], hx, hx[:4])


TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<animNode>
\t<m_Name>{name}</m_Name>
\t<m_AnimName>{clip}</m_AnimName>
\t<m_Looped>{looped}</m_Looped>
\t<m_BlendTime>{fade:.2f}</m_BlendTime>
\t<m_BlendOutTime>{fade:.2f}</m_BlendOutTime>
\t<m_EarlyTransitionOut>{early}</m_EarlyTransitionOut>
\t<m_SpeedScale>{speed}</m_SpeedScale>
\t<m_SyncTrackingEnabled>false</m_SyncTrackingEnabled>
\t<m_ConditionPriority>{priority}</m_ConditionPriority>
\t<m_Conditions x_name="{id0}">
\t\t<m_Name>PerformingAction</m_Name>
\t\t<m_Type>STRING</m_Type>
\t\t<m_Value>PEPerform</m_Value>
\t</m_Conditions>
\t<m_Conditions x_name="{id1}">
\t\t<m_Name>PEPerform</m_Name>
\t\t<m_Type>STRING</m_Type>
\t\t<m_Value>{variant}</m_Value>
\t</m_Conditions>
\t<m_Conditions x_name="{id2}">
\t\t<m_Name>PEHit</m_Name>
\t\t<m_Type>STRING</m_Type>
\t\t<m_Value>{hit}</m_Value>
\t</m_Conditions>
\t<m_Transitions>
\t\t<m_Target>{partner}</m_Target>
\t\t<m_blendInTime>{fade:.2f}</m_blendInTime>
\t\t<m_blendOutTime>{fade:.2f}</m_blendOutTime>
\t</m_Transitions>
</animNode>
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, variant, hit, clip, looped, speed, fade, priority, partner in NODES:
        text = TEMPLATE.format(
            name=name, clip=clip, variant=variant, hit=hit,
            looped="true" if looped else "false",
            early="false" if looped else "true",
            speed=speed if isinstance(speed, str) else "%.2f" % speed,
            fade=fade, priority=priority, partner=partner,
            id0=ident(name, 0), id1=ident(name, 1), id2=ident(name, 2),
        )
        path = os.path.join(OUT, name + ".xml")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print("wrote " + path)
    print("%d nodes" % len(NODES))


if __name__ == "__main__":
    main()

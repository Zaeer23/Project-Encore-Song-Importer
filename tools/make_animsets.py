#!/usr/bin/env python3
"""Write the performance AnimSet nodes.

    python tools/make_animsets.py

The guitar and the singer are Project Encore's own clips, because the base game has no clip of anyone playing a guitar or
singing: tools/build_guitar_anim.py writes PE_GuitarIdle and PE_GuitarStrum, tools/build_sing_anim.py writes
PE_SingIdle and PE_SingLine. The rest is still recomposed from clips the game already ships:

    drums      Bob_EmoteShiftWeight for the pose, Bob_Attack1Hand01_Hit fast for a stick coming down
    harmonica  Bob_EmoteBlowHarmonica_R: the one real instrument animation in media/anims_X
    keys       Bob_EmoteShiftWeight and a one-handed swing

THE HAND-OVER BETWEEN TWO NODES. Each idle node names its hit node in <m_Transitions> and the other way round, with
the same time to fade in and to fade out, and each node's own BlendTime and BlendOutTime are that same time too.
Without that, going from strumming back to idle faded the strum out in 0.14 s and the idle in over 0.25 s: for a
moment the two weighed well under one between them, and the pose underneath showed through -- the survivor's arms
dropped to their sides and the guitar swung up over their head for a fifth of a second every time a phrase ended
(seen frame by frame in a player's video, 2026-11-13). Vanilla does the same for nodes that hand over to each other
(LoadHandgun -> RackHandgun, the fitness sets).

Each node is picked by three conditions, which is the mechanism vanilla uses for its own action variants:

    PerformingAction = PEPerform     set by setActionAnim in PEPerformAction
    PEPerform        = <variant>     which instrument is being played
    PEHit            = idle | hit    "hit" while notes are landing, "idle" between phrases

The guitar's "hit" node is a loop, not a one-shot: it is the strumming clip, and it runs for as long as notes keep
coming. Its speed is the variable PETempo rather than a number -- the same trick the game's reload nodes play with
ReloadSpeed -- so Encore_Anim.lua can set it from the chart's tempo and the down-strokes land on the song's own
eighth notes. The clip is authored at 120 BPM, so PETempo is bpm / 120.

A pack that ships clips of its own does not need this script: register the instrument with anim = "YourNode" and
Project Encore sets PerformingAction to that instead.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "42", "media", "AnimSets", "player", "actions")

# name, variant, hit-state, clip, looped, speed (a number, or the name of a character variable), fade, priority,
# partner (the node it hands over to, and takes over from)
NODES = [
    # Guitar, bass and rhythm share the guitar clips: the same hold, the same hands. Both are authored at 120 BPM and
    # played at the chart's tempo, so the idle's nod and the strum's strokes are on the song's beat.
    ("PE_Guitar_Idle", "guitar", "idle", "PE_GuitarIdle", True, "PETempo", 0.16, 120, "PE_Guitar_Hit"),
    ("PE_Guitar_Hit", "guitar", "hit", "PE_GuitarStrum", True, "PETempo", 0.16, 130, "PE_Guitar_Idle"),

    ("PE_Drums_Idle", "drums", "idle", "Bob_EmoteShiftWeight", True, 0.70, 0.08, 120, "PE_Drums_Hit"),
    ("PE_Drums_Hit", "drums", "hit", "Bob_Attack1Hand01_Hit", False, 2.40, 0.08, 130, "PE_Drums_Idle"),

    # A singer with a microphone: held under the chin between lines, at the mouth while singing. Both at the
    # chart's tempo, like the guitar.
    ("PE_Vocals_Idle", "vocals", "idle", "PE_SingIdle", True, "PETempo", 0.22, 120, "PE_Vocals_Hit"),
    ("PE_Vocals_Hit", "vocals", "hit", "PE_SingLine", True, "PETempo", 0.22, 130, "PE_Vocals_Idle"),

    ("PE_Harmonica_Idle", "harmonica", "idle", "Bob_EmoteBlowHarmonica_R", True, 0.80, 0.18, 120, "PE_Harmonica_Hit"),
    ("PE_Harmonica_Hit", "harmonica", "hit", "Bob_EmoteBlowHarmonica_R", False, 1.30, 0.18, 130, "PE_Harmonica_Idle"),

    ("PE_Keys_Idle", "keys", "idle", "Bob_EmoteShiftWeight", True, 0.60, 0.08, 120, "PE_Keys_Hit"),
    ("PE_Keys_Hit", "keys", "hit", "Bob_Attack1Hand01_Hit", False, 2.20, 0.08, 130, "PE_Keys_Idle"),
]


# Deterministic x_name values. The engine wants a unique id per condition and does not care what it is; generating
# them from the node name keeps a rerun of this script from churning the files.
def ident(node, index):
    h = 0
    for ch in "%s/%d" % (node, index):
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    hx = "%08x" % h
    return "%s-%s-4%s-8%s-%s%s" % (hx, hx[:4], hx[1:4], hx[2:5], hx, hx[:4])


TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<!-- Written by tools/make_animsets.py. Edit that, not this. -->
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
            # A loop has no end to leave early from; a one-shot (a drum stroke) may hand back before it finishes.
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

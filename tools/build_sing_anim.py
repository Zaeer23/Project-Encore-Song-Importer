#!/usr/bin/env python3
"""The singer's clips: a survivor with a microphone, between lines and singing.

    python tools/build_sing_anim.py          -> 42/media/anims_X/Bob/PE_SingIdle.X, PE_SingLine.X
    python tools/build_sing_anim.py view     -> contact sheets in tools/out/ (singidle.png, singline.png)

Same toolkit and same method as tools/build_guitar_anim.py (read its header first): whole-body key poses solved with
two-bone IK, the held thing placed by keying Bip01_Prop1, every frame solved twice -- once for the body, to find out
where the head has gone, and again with the hands sent to it.

Written from scratch on 2026-11-13, replacing two vanilla emotes (a weight shift and a casual salute) that the player
rightly called bad: nothing about either said "singing".

THE MICROPHONE. The game has one: item Base.Microphone, model script "Microphone" (mesh WorldItems/Microphone.fbx,
scale 0.125). It is a world item and has no in-hand placement, but a timed action can put any model script in a hand
by name (setOverrideHandModels("PaintBrush") is how vanilla's painting does it), and Bip01_Prop1 is an ordinary bone
these clips key. The mesh lies on its side as a world item does: 19.5 units long along X with the grille at -X, its
origin in the middle of the handle, resting on Z = 0. So the clips put Prop1 -- the mesh origin, the middle of the
handle -- in the fist, and point -X at the singer's mouth. The size it is drawn at in a hand is not something the
toolkit can read; it is calibrated against the two world items vanilla does put in hands (Bottle_Crafted and
Jar_Crafted come out at a bottle's and a jar's size with the same factor, MIC_K below), and the mouth is aimed a
little short of the lips, so if the real size is off the mic sits a touch off the mouth rather than in the face.

THE MIC FOLLOWS THE HEAD. Its target is worked out from the head bone every frame, so when the singer nods or leans
into a line the hand goes with the mouth, the way a singer's does. The other hand is free: hanging and swinging a
little between lines, and while singing reaching out on the beat and coming back in, a different reach on each beat
of the bar.

TWO CLIPS, ONE STANCE, BOTH AT 120 BPM. PE_SingIdle is a bar of standing between lines: the mic down at the chest,
the weight going side to side, the head nodding on the beat, the eyes going across the room. PE_SingLine is a bar of
singing: leaning into the mic, the knees giving on each beat, the free hand out and in. Both run at PETempo, like the
guitar, so the nod and the reach are on the song's beat.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import build_guitar_anim as GA  # noqa: E402  (the toolkit's paths, the context, the helpers)

K, P, X = GA.K, GA.P, GA.X
FPS = GA.FPS
OUT = GA.OUT
SHEETS = GA.SHEETS
MIC_MESH = os.path.join(os.path.dirname(GA.GUITAR_MESH), "..", "..", "WorldItems", "Microphone.fbx")

# --------------------------------------------------------------------------------------------------------------------- the microphone
MIC_SCRIPT_SCALE = 0.125                  # the model script's scale
MIC_K = 0.06                              # model units per mesh unit after that scale: a crafted bottle comes out 0.15
MIC_UNITS = 19.46                         # the mesh's length along X
MIC_HALF = MIC_UNITS * MIC_SCRIPT_SCALE * MIC_K * 0.5      # the fist (the mesh origin) to the grille: about 0.073
MIC_AXIS_UP = 2.2 * MIC_SCRIPT_SCALE * MIC_K              # how far the mesh's axis sits above its origin at the middle

# The mouth, in the head bone's own frame (x up the head, y to the left, z out of the face), read off the Bob model.
MOUTH_LOCAL = (0.026, 0.0, 0.060)
LIPS_GAP = 0.022                          # the grille sits this far in front of the mouth


def stance(**kw):
    """Standing to sing: feet a shoulder apart and square to the front, the knees soft, the chest up."""
    p = dict(pel=(0.0, 0.0, -0.012), pel_yaw=0.0, pel_pitch=1.0, twist=0.0, lean=2.0, bend=0.0,
             LF=dict(p=(-0.012, 0.092, K.ANKLE_H), yaw=10.0, pitch=0.0),
             RF=dict(p=(-0.028, -0.092, K.ANKLE_H), yaw=-12.0, pitch=0.0),
             look=(1.0, 0.0, 0.80))
    p.update(kw)
    return p


HOME = stance()


# --------------------------------------------------------------------------------------------------------------------- the body
# Curves, not poses, for the reason in build_guitar_anim.py's "the groove": sampled every frame and periodic in the
# clip. The singer moves more than the guitarist -- nothing to keep steady in front of them but a mic that follows
# the mouth anyway.

def body_keys_idle():
    """One bar at 120 BPM between lines: the weight rocking side to side across it, a nod on each beat, the eyes
    going across the room, the free heel coming up as the weight leaves it."""
    def at(t):
        dip = GA.beat_dip(t)
        sw = math.sin(2.0 * math.pi * t / 2.0)
        look_s = 0.35 * math.sin(2.0 * math.pi * (t + 0.25) / 2.0)
        base = stance()
        return stance(pel=(0.0, 0.016 * sw, -0.012 - 0.010 * dip), pel_roll=3.0 * sw, pel_yaw=3.0 * sw,
                      twist=-2.0 * sw, bend=-1.5 * sw, lean=1.8 + 1.0 * dip,
                      look=(1.0, look_s, 0.80 - 0.05 * dip),
                      LF=GA.heel(base["LF"], max(0.0, -sw) ** 1.5 * 0.6),
                      RF=GA.heel(base["RF"], max(0.0, sw) ** 1.5 * 0.6))
    return GA.dense(at, 2.0)


def body_keys_line():
    """One bar of singing: the hips across and back every two beats, the knees driving down on each one, leaning
    into the mic, the shoulders turning out with the free hand's reach and back."""
    def at(t):
        dip = GA.beat_dip(t)
        b = t / 0.5
        sw = math.sin(math.pi * b)
        turn = 4.5 * math.cos(math.pi * b)
        base = stance()
        return stance(pel=(0.005 * dip, 0.022 * sw, -0.012 - 0.028 * dip), pel_yaw=7.0 * sw, pel_roll=4.5 * sw,
                      twist=turn, bend=-2.5 * sw, lean=5.0 + 3.0 * dip,
                      look=(0.95, 0.04 * turn / 4.5, 0.74 - 0.06 * dip),
                      LF=GA.heel(base["LF"], max(0.0, -sw) ** 1.5),
                      RF=GA.heel(base["RF"], max(0.0, sw) ** 1.5))
    return GA.dense(at, 2.0)


# --------------------------------------------------------------------------------------------------------------------- the free hand
def free_hand_idle(t):
    """Hanging at the side, swinging forward a little with the sway."""
    swing = math.sin(2.0 * math.pi * t / 2.0)
    # a little short of straight, so the elbow has a side to bend to and does not flick from one to the other
    return dict(p=(0.030 + 0.022 * swing, 0.160, 0.495), dir=(0.20, 0.04, -1.0), palm=(0.0, -1.0, 0.0),
                reach=0.0, pole=(-0.35, 0.60, -0.20), fist=0.22)


# Where the free hand reaches on each beat of a line: out, in, out and up, in. (f, s, h) of the wrist, the way the
# fingers point, and the way the palm faces.
LINE_REACHES = [
    ((0.180, 0.230, 0.660), (0.55, 0.70, 0.20), (0.25, 0.10, 1.00)),
    ((0.120, 0.090, 0.560), (0.55, -0.40, 0.15), (0.10, 0.00, 1.00)),
    ((0.150, 0.250, 0.760), (0.40, 0.70, 0.55), (0.50, 0.20, 0.80)),
    ((0.110, 0.110, 0.540), (0.55, -0.35, 0.05), (0.05, -0.10, 1.00)),
]


def free_hand_line(t):
    t = t % 2.0
    beat = int(t / 0.5)
    u = (t - beat * 0.5) / 0.5
    a = LINE_REACHES[beat]
    b = LINE_REACHES[(beat + 1) % 4]
    # out on the beat and held, then over to the next one in the second half of the beat
    k = 0.0 if u < 0.45 else ((u - 0.45) / 0.55)
    k = k * k * (3 - 2 * k)
    lerp = lambda x, y: tuple(x[i] + (y[i] - x[i]) * k for i in range(3))  # noqa: E731
    return dict(p=lerp(a[0], b[0]), dir=lerp(a[1], b[1]), palm=lerp(a[2], b[2]),
                reach=0.25, pole=(-0.20, 0.80, -0.45), fist=0.12)


# --------------------------------------------------------------------------------------------------------------------- the mic hand
# Where the grille is against the mouth, and the way the mic runs from the grille down to the handle, in the ground
# frame (f, s, h). Singing, it is at the lips with the handle down and a little out; between lines it is down at the
# chest, tipped back towards the chin.
MIC_LINE = dict(drop=0.004, out=LIPS_GAP, axis=(0.36, -0.20, -0.91))
MIC_IDLE = dict(drop=0.125, out=0.095, axis=(0.55, -0.28, -0.79))


def mic_hand_dir(axis):
    """The fist wraps the handle: the knuckles across it to the left and forward, the palm back towards the face."""
    d = P.norm(GA.gw((0.45, 0.75, 0.15)))
    return GA.wg(d)


def solve(ctx, body, free_hand, mic, t):
    params = K.params_at(body, t)
    W = ctx.pose(params).world()                         # pass one: the body, to find the head
    o = (ctx.pel0[0], 0.0, ctx.pel0[2])

    mouth = X.xform(MOUTH_LOCAL, W["Bip01_Head"])
    face = P.norm(X.xform_dir((0.0, 0.0, 1.0), W["Bip01_Head"]))
    up = P.UP
    grille = P.add(mouth, P.add(P.mul(face, mic["out"]), P.mul(up, -mic["drop"])))
    axis = P.norm(GA.gw(mic["axis"]))                    # grille -> handle, model space
    grip = P.add(grille, P.mul(axis, MIC_HALF))          # the middle of the handle: where the fist goes

    # the free hand
    fh = free_hand(t)
    params["LH"] = dict(p=fh["p"], dir=fh["dir"], roll=GA.roll_for("L", fh["dir"], fh["palm"]),
                        reach=fh["reach"], pole=fh["pole"])

    # the mic hand: aim the wrist so that the grip inside the fist lands on the handle. The grip is a fixed point of
    # the hand, so a couple of corrections converge.
    r_dir = mic_hand_dir(mic["axis"])
    r_palm = (-0.75, 0.45, 0.10)
    target = GA.wg(P.sub(grip, o))
    wrist = target
    for _ in range(4):
        # the elbow down and a little out: a singer's, not a chicken wing
        params["RH"] = dict(p=wrist, dir=r_dir, roll=GA.roll_for("R", r_dir, r_palm), reach=0.20,
                            pole=(0.05, -0.50, -1.00))
        params["fist"] = dict(L=fh["fist"], R=0.85)
        pose = ctx.pose(params)
        held = P.pos(P.place(ctx.prop_off["Bip01_Prop1"], pose.world()["Bip01_R_Hand"]))
        miss = GA.wg(P.sub(grip, held))
        wrist = tuple(wrist[i] + miss[i] for i in range(3))
    params["RH"]["p"] = wrist
    pose = ctx.pose(params)

    # the mic itself: the mesh's X along the handle (its grille at -X, so +X runs grille -> handle), its "up" (the
    # world item's Z, which the game turns into the model's Y) out of the face, and its origin pulled back by the
    # height its axis sits above it, so the axis and not the mesh's resting edge goes through the fist
    held = P.pos(P.place(ctx.prop_off["Bip01_Prop1"], pose.world()["Bip01_R_Hand"]))
    x = axis
    y = P.norm(P.sub(face, P.mul(x, P.dot(face, x))))
    z = P.cross(x, y)
    origin = P.sub(held, P.mul(y, MIC_AXIS_UP))
    pose.set_world("Bip01_Prop1", P.frame(origin, x, y, z))
    pose.mic_grille = grille
    pose.mic_mouth = mouth
    return pose


FREE_ARM = ["Bip01_L_Clavicle", "Bip01_L_UpperArm", "Bip01_L_Forearm", "Bip01_L_Hand"]


def smooth_loop(frames, bones, passes=3, keep=0.4):
    """K.smooth_bones, but round the loop: the frames at the end are smoothed against the ones at the start."""
    pad = 4
    ext = [f.copy() for f in frames[-pad:]] + frames + [f.copy() for f in frames[:pad]]
    K.smooth_bones(ext, bones, passes=passes, keep=keep)
    for i, f in enumerate(frames):
        for b in bones:
            f.local[b] = ext[i + pad].local[b]
        f._world = None


def build_clip(ctx, body, free_hand, mic, seconds):
    n = int(round(seconds * FPS))
    frames = [solve(ctx, body, free_hand, mic, i / float(FPS)) for i in range(n)]
    # The free hand has no exact place to be, so its arm can be eased: the two-bone solver picks the elbow's swing
    # frame by frame, and on a reach that is a flick. The mic arm is not touched -- the mic has to stay at the mouth.
    smooth_loop(frames, [b for b in FREE_ARM if b in frames[0].local])
    frames.append(frames[0].copy())
    return frames


CLIPS = {
    "PE_SingIdle": (body_keys_idle, free_hand_idle, MIC_IDLE, 2.0),
    "PE_SingLine": (body_keys_line, free_hand_line, MIC_LINE, 2.0),
}


def build():
    import armik
    ctx = GA.context()
    # No arm-strain scoring here, and every clip starts from the elbow straight down its pole. The scoring picks the
    # elbow's swing from a set of candidates, remembering the last one; this solver calls the IK several times a
    # frame while it brings the mic to the mouth, which jostles that memory, and the elbow flicked 24 degrees from
    # one frame to the next. With the pole alone it moves smoothly.
    ctx.strain = None
    os.makedirs(OUT, exist_ok=True)
    made = {}
    for name, (body, free_hand, mic, seconds) in CLIPS.items():
        armik._last.clear()
        armik._last.update({"L": 0.0, "R": 0.0})
        frames = build_clip(ctx, body(), free_hand, mic, seconds)
        GA.report(name, frames)
        gaps = [P.length(P.sub(f.mic_grille, f.mic_mouth)) for f in frames if hasattr(f, "mic_grille")]
        if gaps:
            print("   grille to mouth %.3f..%.3f" % (min(gaps), max(gaps)))
        P.write_anim(os.path.join(OUT, name + ".X"), name, frames, FPS, base_clip="Bob_AttackPunch01_Hit")
        print("wrote", os.path.join(OUT, name + ".X"))
        made[name] = frames
    return ctx, made


# --------------------------------------------------------------------------------------------------------------------- looking at it
def mic_verts():
    """The mic mesh in the model's units, in Prop1's frame: the world item's Z turned into Y, as the game draws it."""
    sys.path.insert(0, os.path.join(GA.TOOLKIT, "casualties-assets"))
    import fbxfile as F
    m = F.SkinnedMesh(os.path.normpath(MIC_MESH))
    s = MIC_SCRIPT_SCALE * MIC_K
    verts = [(v[0] * s, v[2] * s, -v[1] * s) for v in m.verts]
    return verts, m.faces


def view():
    import anim_check as A
    import xrender as R
    from PIL import ImageDraw

    ctx, made = build()
    body = A.body()
    faces, cols = [], []
    for fi, f in enumerate(body.mesh.faces):
        part = body.face_part[fi]
        if part == "Dress":
            continue
        faces.append(f)
        cols.append((170, 80, 70) if part in ("RightArm", "RightHand") else (80, 120, 170) if part in ("LeftArm", "LeftHand")
                    else (200, 160, 130) if part == "Head" else (52, 52, 64))
    mv, mf = mic_verts()
    os.makedirs(SHEETS, exist_ok=True)
    for name, frames in made.items():
        idxs = [int(round(k * (len(frames) - 1) / 5.0)) for k in range(5)]
        imgs = []
        for yaw in (180, 225, 135, 90):
            for i in idxs:
                W = frames[i].world()
                gv = [X.xform(v, W["Bip01_Prop1"]) for v in mv]
                layers = [(R.skin(body.mesh, W), faces, cols), (gv, mf, (225, 225, 230))]
                f = R.view_matrix(yaw, 14)
                mid = W["Bip01_Spine1"][12:15] if "Bip01_Spine1" in W else W["Bip01_Pelvis"][12:15]
                c = f((mid[0], mid[1] + 0.10, mid[2]))
                im, _s, _c = R.render(layers, size=(250, 330), yaw=yaw, pitch=14, scale=300, center=(c[0], c[1]), bg=(70, 100, 40))
                ImageDraw.Draw(im).text((4, 4), "%s f%d yaw%d" % (name[3:], i, yaw), fill=(255, 255, 255))
                imgs.append(im)
        out = os.path.join(SHEETS, name.lower()[3:] + ".png")
        R.sheet(imgs, len(idxs)).save(out)
        print("sheet", out)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "view":
        view()
    else:
        build()

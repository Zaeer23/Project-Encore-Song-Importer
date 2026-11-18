#!/usr/bin/env python3

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import build_guitar_anim as GA

K, P, X = GA.K, GA.P, GA.X
FPS = GA.FPS
OUT = GA.OUT
SHEETS = GA.SHEETS
MIC_MESH = os.path.join(os.path.dirname(GA.GUITAR_MESH), "..", "..", "WorldItems", "Microphone.fbx")

MIC_SCRIPT_SCALE = 0.125
MIC_K = 0.06
MIC_UNITS = 19.46
MIC_HALF = MIC_UNITS * MIC_SCRIPT_SCALE * MIC_K * 0.5
MIC_AXIS_UP = 2.2 * MIC_SCRIPT_SCALE * MIC_K

MOUTH_LOCAL = (0.026, 0.0, 0.060)
LIPS_GAP = 0.022


def stance(**kw):
    p = dict(pel=(0.0, 0.0, -0.030), pel_yaw=0.0, pel_pitch=2.0, twist=0.0, lean=3.0, bend=0.0,
             LF=dict(p=(0.000, 0.112, K.ANKLE_H), yaw=14.0, pitch=0.0),
             RF=dict(p=(-0.034, -0.112, K.ANKLE_H), yaw=-16.0, pitch=0.0),
             look=(1.0, 0.0, 0.80))
    p.update(kw)
    return p


HOME = stance()


def body_keys_idle():
    def at(t):
        dip = GA.beat_dip(t)
        sw = math.sin(2.0 * math.pi * t / 2.0)
        look_s = 0.35 * math.sin(2.0 * math.pi * (t + 0.25) / 2.0)
        base = stance()
        return stance(pel=(0.0, 0.026 * sw, -0.030 - 0.018 * dip), pel_roll=5.0 * sw, pel_yaw=5.0 * sw,
                      twist=-3.0 * sw, bend=-2.5 * sw, lean=2.6 + 1.6 * dip,
                      look=(1.0, look_s, 0.80 - 0.07 * dip),
                      LF=GA.heel(base["LF"], max(0.0, -sw) ** 1.5 * 0.7),
                      RF=GA.heel(base["RF"], max(0.0, sw) ** 1.5 * 0.7))
    return GA.dense(at, 2.0)


def body_keys_line():
    def at(t):
        dip = GA.beat_dip(t)
        b = t / 0.5
        sw = math.sin(math.pi * b)
        turn = 4.5 * math.cos(math.pi * b)
        base = stance()
        return stance(pel=(0.007 * dip, 0.032 * sw, -0.030 - 0.040 * dip), pel_yaw=9.0 * sw, pel_roll=6.5 * sw,
                      twist=turn, bend=-3.5 * sw, lean=5.5 + 4.5 * dip,
                      look=(0.95, 0.04 * turn / 4.5, 0.74 - 0.09 * dip),
                      LF=GA.heel(base["LF"], max(0.0, -sw) ** 1.5),
                      RF=GA.heel(base["RF"], max(0.0, sw) ** 1.5))
    return GA.dense(at, 2.0)


def free_hand_idle(t):
    swing = math.sin(2.0 * math.pi * t / 2.0)
    return dict(p=(0.030 + 0.022 * swing, 0.160, 0.495), dir=(0.20, 0.04, -1.0), palm=(0.0, -1.0, 0.0),
                reach=0.0, pole=(-0.35, 0.60, -0.20), fist=0.22)


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
    k = 0.0 if u < 0.45 else ((u - 0.45) / 0.55)
    k = k * k * (3 - 2 * k)
    lerp = lambda x, y: tuple(x[i] + (y[i] - x[i]) * k for i in range(3))
    return dict(p=lerp(a[0], b[0]), dir=lerp(a[1], b[1]), palm=lerp(a[2], b[2]),
                reach=0.25, pole=(-0.20, 0.80, -0.45), fist=0.12)


MIC_LINE = dict(drop=0.004, out=LIPS_GAP, axis=(0.36, -0.20, -0.91))
MIC_IDLE = dict(drop=0.125, out=0.095, axis=(0.55, -0.28, -0.79))


def mic_hand_dir(axis):
    d = P.norm(GA.gw((0.45, 0.75, 0.15)))
    return GA.wg(d)


def solve(ctx, body, free_hand, mic, t):
    params = K.params_at(body, t)
    W = ctx.pose(params).world()
    o = (ctx.pel0[0], 0.0, ctx.pel0[2])

    mouth = X.xform(MOUTH_LOCAL, W["Bip01_Head"])
    face = P.norm(X.xform_dir((0.0, 0.0, 1.0), W["Bip01_Head"]))
    up = P.UP
    grille = P.add(mouth, P.add(P.mul(face, mic["out"]), P.mul(up, -mic["drop"])))
    axis = P.norm(GA.gw(mic["axis"]))
    grip = P.add(grille, P.mul(axis, MIC_HALF))

    fh = free_hand(t)
    params["LH"] = dict(p=fh["p"], dir=fh["dir"], roll=GA.roll_for("L", fh["dir"], fh["palm"]),
                        reach=fh["reach"], pole=fh["pole"])

    r_dir = mic_hand_dir(mic["axis"])
    r_palm = (-0.75, 0.45, 0.10)
    target = GA.wg(P.sub(grip, o))
    wrist = target
    for _ in range(4):
        params["RH"] = dict(p=wrist, dir=r_dir, roll=GA.roll_for("R", r_dir, r_palm), reach=0.20,
                            pole=(0.05, -0.50, -1.00))
        params["fist"] = dict(L=fh["fist"], R=0.85)
        pose = ctx.pose(params)
        held = P.pos(P.place(ctx.prop_off["Bip01_Prop1"], pose.world()["Bip01_R_Hand"]))
        miss = GA.wg(P.sub(grip, held))
        wrist = tuple(wrist[i] + miss[i] for i in range(3))
    params["RH"]["p"] = wrist
    pose = ctx.pose(params)

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


def mic_verts():
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

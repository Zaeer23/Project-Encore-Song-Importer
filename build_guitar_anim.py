#!/usr/bin/env python3

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
TOOLKIT = r"C:\Users\iamab\Desktop\Zomboid Mods\tools"
for _p in (os.path.join(TOOLKIT, "casualties-assets"), os.path.join(TOOLKIT, "gunsmithing-assets")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ikanim as K
import xfile as X
import xpose as P

FPS = 30
OUT = os.path.join(MOD, "42", "media", "anims_X", "Bob")
SHEETS = os.path.join(MOD, "tools", "out")
GUITAR_MESH = os.path.join(P.VAN, "models_X", "weapons", "2handed", "Guitar_ElectricBlack.X")

BODY_CENTRE = (0.118, -0.050, 0.552)
BODY_Y = 0.455
NECK_DIR = (0.20, 0.87, 0.45)
FACE_DIR = (0.95, -0.08, 0.30)

FRET_NEAR = 0.150
FRET_FAR = 0.215
STRUM_Y = 0.425
STRUM_TOP = 0.052
STRUM_BOTTOM = -0.030
STRUM_REST = 0.018
REST_Y = 0.465


def gw(p):
    return (p[1], p[2], -p[0])


def wg(v):
    return (-v[2], v[0], v[1])


class Guitar:
    def __init__(self, ctx, home):
        self.ctx = ctx
        o = (ctx.pel0[0], 0.0, ctx.pel0[2])
        self.o = o
        n = P.norm(gw(NECK_DIR))
        z = gw(FACE_DIR)
        z = P.norm(P.sub(z, P.mul(n, P.dot(z, n))))
        y = P.mul(n, -1.0)
        x = P.cross(y, z)
        centre = P.add(o, gw(BODY_CENTRE))
        origin = P.add(centre, P.mul(n, BODY_Y))
        G0 = P.frame(origin, x, y, z)
        self.up_sign = 1.0 if x[1] > 0 else -1.0
        W = ctx.pose(home).world()
        self.rel = P.relative(G0, W["Bip01_Spine"])

    def world(self, W):
        return P.place(self.rel, W["Bip01_Spine"])

    def point(self, G, along, up, off):
        p = X.xform((up * self.up_sign, along, off), G)
        return wg(P.sub(p, self.o))

    def direction(self, G, along, up, off):
        d = X.xform_dir((up * self.up_sign, along, off), G)
        return wg(d)


def roll_for(side, direction, palm):
    z0 = P.mul(K.LEFT, -1.0 if side == "L" else 1.0)
    d = P.norm(gw(direction))
    R = P.rot_between(P.FWD, d)
    z = P.apply3(R, z0)
    want = gw(palm)
    want = P.norm(P.sub(want, P.mul(d, P.dot(want, d))))
    return math.degrees(math.atan2(P.dot(P.cross(z, want), d), P.dot(z, want)))


def stance(**kw):
    p = dict(pel=(0.0, 0.0, -0.034), pel_yaw=-6.0, pel_pitch=2.5, twist=7.0, lean=4.0, bend=0.0,
             LF=dict(p=(0.004, 0.118, K.ANKLE_H), yaw=18.0, pitch=0.0),
             RF=dict(p=(-0.052, -0.122, K.ANKLE_H), yaw=-24.0, pitch=0.0),
             look=(0.70, 0.10, 0.74))
    p.update(kw)
    return p


HOME = stance()
LOOK_NECK = (0.42, 0.44, 0.60)
LOOK_OUT = (0.80, -0.05, 0.76)


def dense(fn, seconds):
    n = int(round(seconds * FPS))
    return [(i / float(FPS), fn(i / float(FPS)), "linear") for i in range(n + 1)]


def beat_dip(t):
    u = 0.5 + 0.5 * math.cos(2.0 * math.pi * t / 0.5)
    return u ** 1.4


def heel(on, up):
    f, side, h = on["p"]
    lift = max(0.0, up - 0.45) / 0.55
    return dict(p=(f + 0.008 * up + 0.026 * lift, side, h + 0.030 * up + 0.046 * lift), yaw=on["yaw"],
                pitch=24.0 * up - 14.0 * lift)


def groove(t, sway_period, sway_hips, sway_roll, dip_depth, lean0, lean_dip, look0, look1=None, look_mix=None,
           heel_amount=1.0):
    dip = beat_dip(t)
    sw = math.sin(2.0 * math.pi * t / sway_period)
    look = look0
    if look1 is not None:
        m = look_mix(t)
        look = tuple(look0[i] + (look1[i] - look0[i]) * m for i in range(3))
    look = (look[0], look[1] - 0.08 * sw, look[2] - 0.10 * dip)
    base = stance()
    left_up = max(0.0, -sw) ** 1.5 * heel_amount
    right_up = max(0.0, sw) ** 1.5 * heel_amount
    return stance(pel=(0.006 * dip, sway_hips * sw, -0.034 - dip_depth * dip),
                  pel_yaw=-6.0 + 8.0 * sw, pel_roll=sway_roll * sw,
                  twist=7.0 - 6.0 * sw, bend=-3.5 * sw, lean=lean0 + lean_dip * dip, look=look,
                  LF=heel(base["LF"], left_up), RF=heel(base["RF"], right_up))


def body_keys_idle():
    def at(t):
        return groove(t, sway_period=2.0, sway_hips=0.030, sway_roll=6.0, dip_depth=0.026, lean0=4.0, lean_dip=3.5,
                      look0=LOOK_NECK, look1=LOOK_OUT,
                      look_mix=lambda t: 0.5 - 0.5 * math.cos(2.0 * math.pi * t / 2.0), heel_amount=0.8)
    return dense(at, 2.0)


def body_keys_strum():
    def at(t):
        return groove(t, sway_period=1.0, sway_hips=0.030, sway_roll=6.0, dip_depth=0.040, lean0=4.5, lean_dip=5.5,
                      look0=(0.66, 0.18, 0.68))
    return dense(at, 1.0)


def wave(t, period, lo, hi, sharp=1.0):
    u = 0.5 - 0.5 * math.cos(2.0 * math.pi * (t % period) / period)
    if sharp != 1.0:
        u = u ** sharp / (u ** sharp + (1.0 - u) ** sharp)
    return lo + (hi - lo) * u


def step_between(t, t0, t1, a, b):
    if t <= t0:
        return a
    if t >= t1:
        return b
    u = (t - t0) / (t1 - t0)
    return a + (b - a) * (u * u * (3 - 2 * u))


def hands_idle(t):
    t = t % 2.0
    if t < 1.5:
        fret = step_between(t, 0.86, 1.0, FRET_NEAR, FRET_FAR)
    else:
        fret = step_between(t, 1.86, 2.0, FRET_FAR, FRET_NEAR)
    beat = (t % 0.5) / 0.5
    tap = math.sin(math.pi * (beat - 0.8) / 0.2) if beat > 0.8 else 0.0
    strum = STRUM_REST - 0.010 + 0.012 * tap
    lift = 0.028 + 0.016 * tap
    return fret, strum, lift, REST_Y


def hands_strum(t):
    cycle = (t % 0.25) / 0.25
    if cycle < 0.42:
        u = cycle / 0.42
        strum = STRUM_TOP + (STRUM_BOTTOM - STRUM_TOP) * (u * u * (3 - 2 * u))
        lift = 0.030
    else:
        u = (cycle - 0.42) / 0.58
        strum = STRUM_BOTTOM + (STRUM_TOP - STRUM_BOTTOM) * (u * u * (3 - 2 * u))
        lift = 0.030 + 0.012 * math.sin(math.pi * u)
    fret = wave(t, 1.0, FRET_NEAR + 0.01, FRET_FAR - 0.01, 3.0)
    return fret, strum, lift, STRUM_Y


def solve(ctx, guitar, body, hands, t):
    params = K.params_at(body, t)
    G = guitar.world(ctx.pose(params).world())
    fret, strum, lift, along = hands(t)

    l_dir = guitar.direction(G, -0.10, 0.45, 1.0)
    l_palm = guitar.direction(G, 0.0, 1.0, 0.15)
    params["LH"] = dict(p=guitar.point(G, fret, -0.040, -0.046), dir=l_dir, roll=roll_for("L", l_dir, l_palm),
                        reach=0.55, pole=(-0.15, 0.55, -1.0))
    r_dir = guitar.direction(G, -0.18, -1.0, -0.22)
    r_palm = guitar.direction(G, 0.0, -0.25, -1.0)
    params["RH"] = dict(p=guitar.point(G, along, strum + 0.050, lift + 0.012), dir=r_dir,
                        roll=roll_for("R", r_dir, r_palm), reach=0.25, pole=(-0.55, -1.0, 0.10))
    params["fist"] = dict(L=0.78, R=0.45)

    pose = ctx.pose(params)
    pose.set_world("Bip01_Prop1", guitar.world(pose.world()))
    return pose


def build_clip(ctx, guitar, body, hands, seconds):
    n = int(round(seconds * FPS))
    frames = [solve(ctx, guitar, body, hands, i / float(FPS)) for i in range(n)]
    frames.append(frames[0].copy())
    return frames


def report(name, frames):
    steps = K.max_steps(frames, K.ARM_BONES + K.LEG_BONES + K.SPINE_BONES)
    worst = max(steps.items(), key=lambda kv: kv[1][0])
    errs = [max(getattr(f, "errs", {}).values() or [0.0]) for f in frames]
    slide = K.foot_slide(frames, FPS)
    print("%-16s %3d frames  hand/foot miss %.4f  fastest bone %-14s %4.1f deg/frame @%d  foot slide %.4f" % (
        name, len(frames), max(errs), worst[0][6:], worst[1][0], worst[1][1], slide[0]))
    return max(errs), worst[1][0]


CLIPS = {
    "PE_GuitarIdle": (body_keys_idle, hands_idle, 2.0),
    "PE_GuitarStrum": (body_keys_strum, hands_strum, 1.0),
}


def context():
    ctx = K.Context()
    try:
        import build_reload_anims as BR
        ctx.strain = lambda q, sd: BR.strain(q, sd)
        ctx.ease_wrists = None
    except Exception as exc:
        print("note: no arm strain scoring (%s)" % exc)
    return ctx


def build():
    ctx = context()
    guitar = Guitar(ctx, HOME)
    os.makedirs(OUT, exist_ok=True)
    made = {}
    for name, (body, hands, seconds) in CLIPS.items():
        frames = build_clip(ctx, guitar, body(), hands, seconds)
        report(name, frames)
        P.write_anim(os.path.join(OUT, name + ".X"), name, frames, FPS, base_clip="Bob_AttackPunch01_Hit")
        print("wrote", os.path.join(OUT, name + ".X"))
        made[name] = frames
    return ctx, guitar, made


def view():
    import anim_check as A
    import xrender as R
    from PIL import ImageDraw

    ctx, guitar, made = build()
    body = A.body()
    faces, cols = [], []
    for fi, f in enumerate(body.mesh.faces):
        part = body.face_part[fi]
        if part == "Dress":
            continue
        faces.append(f)
        cols.append((170, 80, 70) if part in ("RightArm", "RightHand") else (80, 120, 170) if part in ("LeftArm", "LeftHand")
                    else (200, 160, 130) if part == "Head" else (52, 52, 64))
    gm = X.Mesh(X.find_mesh_frames(X.load(GUITAR_MESH))[0])
    os.makedirs(SHEETS, exist_ok=True)
    for name, frames in made.items():
        idxs = [int(round(k * (len(frames) - 1) / 5.0)) for k in range(5)] if "Idle" in name else [0, 2, 4, 6, 8]
        imgs = []
        for yaw in (180, 225, 135, 90):
            for i in idxs:
                W = frames[i].world()
                gv = [X.xform(v, W["Bip01_Prop1"]) for v in gm.verts]
                layers = [(R.skin(body.mesh, W), faces, cols), (gv, gm.faces, (215, 175, 60))]
                f = R.view_matrix(yaw, 14)
                mid = W["Bip01_Pelvis"][12:15]
                c = f((mid[0], mid[1] + 0.08, mid[2]))
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

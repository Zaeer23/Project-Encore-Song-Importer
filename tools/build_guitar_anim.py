#!/usr/bin/env python3
"""The guitar clips: a survivor actually playing the thing, and holding it like one.

    python tools/build_guitar_anim.py          -> 42/media/anims_X/Bob/PE_GuitarIdle.X, PE_GuitarStrum.X
    python tools/build_guitar_anim.py view     -> contact sheets in tools/out/ (guitaridle.png, guitarstrum.png)

Needs the IK toolkit in  Desktop/Zomboid Mods/tools  (ikanim, xpose, xfile, xrender, anim_check: the same one
Gunsmithing's finishing moves are built with), and Pillow for the `view` sheets.

What had to be solved, because the base game does none of it:

THE HOLD. A guitar in Zomboid is a two-handed weapon, so it rides Bip01_Prop1 in the right fist, held by the neck
like a bat. The mesh (Guitar_ElectricBlack.X, identity frame) has its origin at the headstock end, runs +Y to the
body (0.61 units, the body from about 0.30), is 0.2 wide in X, and its string face is +Z: the neck stands proud of
the body top on that side. Nothing in the engine re-poses a held item, but a clip can: Bip01_Prop1 is an ordinary
animated bone, so these clips key it off the hand and across the body (body at the right hip, neck up and to the
left at about 27 degrees, strings facing out) and then solve both arms to the guitar instead of the guitar to an
arm. The guitar is carried by the lower spine, not by either hand, so when the hips sway it sways with them the way
a strapped guitar does, and neither hand ever drags it.

THE HANDS. Every hand target is written in the guitar's own coordinates (along the neck, across the strings, off the
face), which is the only frame in which "on the third fret" or "over the pickups" means anything. Each frame is
solved twice: once for the body alone, to find out where the spine has put the guitar, and again with the hands sent
to it. The arms never move the spine, so the second pass is exact.

TWO CLIPS, ONE POSE. PE_GuitarIdle is one bar of 4/4 at 120 BPM of grooving between phrases: the knees give on
every beat and more on one and three, the head nods with them, the hips sway across the bar, the eyes go down to the
neck and up at the room, the fretting hand moves up a position on three and back on one, and the picking hand rests
on the strings by the bridge, lifting to tap the time just before each beat. PE_GuitarStrum is a one-second loop of
four down-up strokes, eighth notes at 120 BPM, with the head nodding on the beat. Both run at PETempo (the chart's
tempo over 120), so the nod and the strokes are on the song's own beat. They share the guitar's placement and the
stance exactly, so the game's blend between them is a hand starting to move and nothing else.

(The idle used to be a two-second weight shift at a fixed speed that looked nearly the same as the strum held
still. The hand-over between the two clips is in tools/make_animsets.py: it used to dip through the game's own
pose, which is what put the guitar over the survivor's head at the end of every phrase.)
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
TOOLKIT = r"C:\Users\iamab\Desktop\Zomboid Mods\tools"
for _p in (os.path.join(TOOLKIT, "casualties-assets"), os.path.join(TOOLKIT, "gunsmithing-assets")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ikanim as K  # noqa: E402
import xfile as X  # noqa: E402
import xpose as P  # noqa: E402

FPS = 30
OUT = os.path.join(MOD, "42", "media", "anims_X", "Bob")
SHEETS = os.path.join(MOD, "tools", "out")
GUITAR_MESH = os.path.join(P.VAN, "models_X", "weapons", "2handed", "Guitar_ElectricBlack.X")

# --------------------------------------------------------------------------------------------------------------------- the guitar, in the ground frame
# (f forward, s left, h up; model units: a person is 0.98 of them tall)
BODY_CENTRE = (0.118, -0.050, 0.552)      # the middle of the guitar's body: in front of the right hip
BODY_Y = 0.455                            # where that middle is along the mesh's own +Y
NECK_DIR = (0.20, 0.87, 0.45)             # from the body to the headstock: left, up, a little away from the chest
FACE_DIR = (0.95, -0.08, 0.30)            # the way the strings face: out, tipped up towards the player's eyes

# where the hands go, in the guitar's coordinates: (along the neck from the headstock, up across the strings, off the face)
FRET_NEAR = 0.150                         # the fretting hand's two positions along the neck
FRET_FAR = 0.215
STRUM_Y = 0.425                           # the picking hand: over the pickups
STRUM_TOP = 0.052                         # the top of a stroke, above the strings' middle
STRUM_BOTTOM = -0.030                     # and the bottom of it
STRUM_REST = 0.018                        # where the hand waits between phrases
REST_Y = 0.465                            # and how far along: on the strings just short of the bridge, palm muting


def gw(p):
    """Ground (f, s, h) -> model space, as a direction."""
    return (p[1], p[2], -p[0])


def wg(v):
    """Model space -> ground (f, s, h), as a direction."""
    return (-v[2], v[0], v[1])


class Guitar:
    """The guitar's frame for a body: built once against the home stance, then carried by the lower spine."""

    def __init__(self, ctx, home):
        self.ctx = ctx
        o = (ctx.pel0[0], 0.0, ctx.pel0[2])
        self.o = o
        n = P.norm(gw(NECK_DIR))
        z = gw(FACE_DIR)
        z = P.norm(P.sub(z, P.mul(n, P.dot(z, n))))            # the face square to the neck
        y = P.mul(n, -1.0)                                     # the mesh's +Y runs headstock -> body
        x = P.cross(y, z)
        centre = P.add(o, gw(BODY_CENTRE))
        origin = P.add(centre, P.mul(n, BODY_Y))
        G0 = P.frame(origin, x, y, z)
        # which way along the mesh's X is "up across the strings" for this placement
        self.up_sign = 1.0 if x[1] > 0 else -1.0
        W = ctx.pose(home).world()
        self.rel = P.relative(G0, W["Bip01_Spine"])

    def world(self, W):
        return P.place(self.rel, W["Bip01_Spine"])

    def point(self, G, along, up, off):
        """A point given in the guitar's terms, in the ground frame."""
        p = X.xform((up * self.up_sign, along, off), G)
        return wg(P.sub(p, self.o))

    def direction(self, G, along, up, off):
        d = X.xform_dir((up * self.up_sign, along, off), G)
        return wg(d)


def roll_for(side, direction, palm):
    """The `roll` that turns a hand pointing along `direction` (ground frame) so its palm faces `palm`.
    ikanim builds a hand by turning the reference hand the shortest way onto `dir` and then rolling it about the
    fingers; this works that roll out instead of leaving it to trial and error."""
    z0 = P.mul(K.LEFT, -1.0 if side == "L" else 1.0)
    d = P.norm(gw(direction))
    R = P.rot_between(P.FWD, d)
    z = P.apply3(R, z0)
    want = gw(palm)
    want = P.norm(P.sub(want, P.mul(d, P.dot(want, d))))        # the part of it square to the fingers
    return math.degrees(math.atan2(P.dot(P.cross(z, want), d), P.dot(z, want)))


# --------------------------------------------------------------------------------------------------------------------- the stance
def stance(**kw):
    """Standing to play: feet a little apart and turned out, the knees soft, the chest turned a touch towards the neck."""
    p = dict(pel=(0.0, 0.0, -0.014), pel_yaw=-6.0, pel_pitch=1.5, twist=7.0, lean=3.0, bend=0.0,
             LF=dict(p=(-0.015, 0.088, K.ANKLE_H), yaw=14.0, pitch=0.0),
             RF=dict(p=(-0.040, -0.094, K.ANKLE_H), yaw=-18.0, pitch=0.0),
             look=(0.70, 0.10, 0.74))
    p.update(kw)
    return p


HOME = stance()
LOOK_NECK = (0.42, 0.44, 0.60)             # down at the fretting hand
LOOK_OUT = (0.80, -0.05, 0.76)             # up at the room


# --------------------------------------------------------------------------------------------------------------------- the groove
# The body is not keyed pose to pose. It used to be -- a pose every half beat, eased between -- and smoothstep easing
# stops dead at every key, so the player stopped eight times a bar and moved like a puppet. Now each part of the body
# is a smooth curve of time, sampled every frame, and every curve is periodic in the clip so the loop has no seam.
#
#   dip    the knees, on every beat: deepest on the beat, up between, a little snappier on the way down
#   sway   the hips across the bar and back, rolling with it, the chest turning against them (an S through the spine)
#   heels  the weight rocks from leg to leg with the sway, and the leg it leaves comes up onto the ball of the foot
#   nod    the head with the knees

def dense(fn, seconds):
    """A key on every frame, straight between them: a curve, not a pose list."""
    n = int(round(seconds * FPS))
    return [(i / float(FPS), fn(i / float(FPS)), "linear") for i in range(n + 1)]


def beat_dip(t):
    """1 on the beat, 0 half way to the next, at 120 BPM."""
    u = 0.5 + 0.5 * math.cos(2.0 * math.pi * t / 0.5)
    return u ** 1.4


def heel(on, up):
    """A foot coming up onto its ball by `up` (0..1): the ankle rises and moves forward a touch over the toes."""
    f, side, h = on["p"]
    return dict(p=(f + 0.008 * up, side, h + 0.030 * up), yaw=on["yaw"], pitch=24.0 * up)


def groove(t, sway_period, sway_hips, sway_roll, dip_depth, lean0, lean_dip, look0, look1=None, look_mix=None,
           heel_amount=1.0):
    dip = beat_dip(t)
    sw = math.sin(2.0 * math.pi * t / sway_period)
    look = look0
    if look1 is not None:
        m = look_mix(t)
        look = tuple(look0[i] + (look1[i] - look0[i]) * m for i in range(3))
    look = (look[0], look[1] - 0.06 * sw, look[2] - 0.07 * dip)
    base = stance()
    left_up = max(0.0, -sw) ** 1.5 * heel_amount       # weight going right: the left heel comes up
    right_up = max(0.0, sw) ** 1.5 * heel_amount
    return stance(pel=(0.004 * dip, sway_hips * sw, -0.012 - dip_depth * dip),
                  pel_yaw=-6.0 + 6.0 * sw, pel_roll=sway_roll * sw,
                  twist=7.0 - 4.0 * sw, bend=-2.5 * sw, lean=lean0 + lean_dip * dip, look=look,
                  LF=heel(base["LF"], left_up), RF=heel(base["RF"], right_up))


def body_keys_idle():
    """One bar of 4/4 at 120 BPM: a slow sway across the whole bar, the knees on every beat, the eyes down at the neck
    for the first half and up at the room for the second."""
    def at(t):
        return groove(t, sway_period=2.0, sway_hips=0.020, sway_roll=3.5, dip_depth=0.016, lean0=3.0, lean_dip=2.5,
                      look0=LOOK_NECK, look1=LOOK_OUT,
                      look_mix=lambda t: 0.5 - 0.5 * math.cos(2.0 * math.pi * t / 2.0), heel_amount=0.8)
    return dense(at, 2.0)


def body_keys_strum():
    """Two beats: the hips across and back once, the knees driving down on each beat, the head with them."""
    def at(t):
        return groove(t, sway_period=1.0, sway_hips=0.018, sway_roll=4.0, dip_depth=0.026, lean0=3.5, lean_dip=4.0,
                      look0=(0.66, 0.18, 0.68))
    return dense(at, 1.0)


def wave(t, period, lo, hi, sharp=1.0):
    """lo at t=0, hi half a period later, eased; `sharp` > 1 makes it spend longer at the ends."""
    u = 0.5 - 0.5 * math.cos(2.0 * math.pi * (t % period) / period)
    if sharp != 1.0:
        u = u ** sharp / (u ** sharp + (1.0 - u) ** sharp)
    return lo + (hi - lo) * u


def step_between(t, t0, t1, a, b):
    """a until t0, b from t1, eased between."""
    if t <= t0:
        return a
    if t >= t1:
        return b
    u = (t - t0) / (t1 - t0)
    return a + (b - a) * (u * u * (3 - 2 * u))


def hands_idle(t):
    """(fret position, strum height, picking hand lift off the face, picking hand along the neck)"""
    t = t % 2.0
    # up a position on beat three, back down on the next bar's one
    if t < 1.5:
        fret = step_between(t, 0.86, 1.0, FRET_NEAR, FRET_FAR)
    else:
        fret = step_between(t, 1.86, 2.0, FRET_FAR, FRET_NEAR)
    # the picking hand rests on the strings and taps the time: up a little in the last fifth of each beat, down on it
    beat = (t % 0.5) / 0.5
    tap = math.sin(math.pi * (beat - 0.8) / 0.2) if beat > 0.8 else 0.0
    strum = STRUM_REST - 0.010 + 0.012 * tap
    lift = 0.028 + 0.016 * tap
    return fret, strum, lift, REST_Y


def hands_strum(t):
    # four strokes a second: down on the eighth, back up in between. The down-stroke is the quicker half.
    cycle = (t % 0.25) / 0.25
    if cycle < 0.42:
        u = cycle / 0.42
        strum = STRUM_TOP + (STRUM_BOTTOM - STRUM_TOP) * (u * u * (3 - 2 * u))
        lift = 0.030
    else:
        u = (cycle - 0.42) / 0.58
        strum = STRUM_BOTTOM + (STRUM_TOP - STRUM_BOTTOM) * (u * u * (3 - 2 * u))
        lift = 0.030 + 0.012 * math.sin(math.pi * u)            # the hand comes off the strings on the way back up
    # the fretting hand changes position once a loop, on the second beat
    fret = wave(t, 1.0, FRET_NEAR + 0.01, FRET_FAR - 0.01, 3.0)
    return fret, strum, lift, STRUM_Y


# --------------------------------------------------------------------------------------------------------------------- frames
def solve(ctx, guitar, body, hands, t):
    params = K.params_at(body, t)
    # pass one: the body alone, to find out where the spine has put the guitar
    G = guitar.world(ctx.pose(params).world())
    fret, strum, lift, along = hands(t)

    # the fretting hand: the wrist under and behind the neck, the fingers coming forward under it and closing up
    # over the fretboard, so the palm faces up across the strings
    l_dir = guitar.direction(G, -0.10, 0.45, 1.0)
    l_palm = guitar.direction(G, 0.0, 1.0, 0.15)
    params["LH"] = dict(p=guitar.point(G, fret, -0.040, -0.046), dir=l_dir, roll=roll_for("L", l_dir, l_palm),
                        reach=0.55, pole=(-0.15, 0.55, -1.0))
    # the picking hand: the forearm over the top of the body, the hand hanging across the strings, palm to the face
    r_dir = guitar.direction(G, -0.18, -1.0, -0.22)
    r_palm = guitar.direction(G, 0.0, -0.25, -1.0)
    params["RH"] = dict(p=guitar.point(G, along, strum + 0.050, lift + 0.012), dir=r_dir,
                        roll=roll_for("R", r_dir, r_palm), reach=0.25, pole=(-0.55, -1.0, 0.10))
    params["fist"] = dict(L=0.78, R=0.45)

    pose = ctx.pose(params)
    # the guitar goes where the spine carries it, not where the right fist would hold a bat
    pose.set_world("Bip01_Prop1", guitar.world(pose.world()))
    return pose


def build_clip(ctx, guitar, body, hands, seconds):
    n = int(round(seconds * FPS))
    frames = [solve(ctx, guitar, body, hands, i / float(FPS)) for i in range(n)]
    frames.append(frames[0].copy())                              # the loop closes on its own first frame
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
    try:                                     # the same arm-naturalness scoring the reload and finisher clips use
        import build_reload_anims as BR
        ctx.strain = lambda q, sd: BR.strain(q, sd)
        ctx.ease_wrists = None               # the wrists here are placed on purpose: easing them pulls the hands off the guitar
    except Exception as exc:                 # noqa: BLE001
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


# --------------------------------------------------------------------------------------------------------------------- looking at it
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
        for yaw in (180, 225, 135, 90):                         # front, front-left, front-right, the player's left side
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

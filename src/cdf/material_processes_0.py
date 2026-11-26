"""
Material processes 0 -- sand pouring as Rhino.Geometry functions for Grasshopper.

Python versions of exercises/material-processes-0/sand_pouring_geometric.ghx:

* sand_ridge_along_curve           -- a sand ridge poured along a curve
                                      (constant radius and height)
* sand_ridge_along_curve_variable  -- several ridges along the same curve, one
                                      per (radius, height) pair
* sand_cones_at_points             -- sand cones of a given volume poured at points,
                                      unioned into piles

Use in a GHPython 3 component, for example:

    from cdf.material_processes_0 import sand_ridge_along_curve
    a = sand_ridge_along_curve(curve, radius, height)

where `curve` is a Curve input (Item Access) and `radius` / `height` are sliders.
"""

import math
import Rhino.Geometry as rg

_BLEND_CONTINUITY = [
    rg.BlendContinuity.Position,
    rg.BlendContinuity.Tangency,
    rg.BlendContinuity.Curvature,
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _offset_curve(curve, distance, tolerance):
    """Offset a curve in World XY with sharp corners and return a single curve."""
    result = curve.Offset(
        rg.Plane.WorldXY, distance, tolerance, rg.CurveOffsetCornerStyle.Sharp
    )
    if not result:
        raise ValueError("Could not offset curve by {}.".format(distance))
    if len(result) > 1:
        result = rg.Curve.JoinCurves(result, tolerance)
    return result[0]


def _blend(curve_a, curve_b, continuity):
    """Blend from the end of curve_a to the start of curve_b (bulge 1, 1)."""
    index = max(0, min(2, int(continuity)))
    return rg.Curve.CreateBlendCurve(curve_a, curve_b, _BLEND_CONTINUITY[index], 1.0, 1.0)


def _flipped(curve):
    copy = curve.DuplicateCurve()
    copy.Reverse()
    return copy


def _loft(curve_a, curve_b, loft_type=rg.LoftType.Normal):
    breps = rg.Brep.CreateFromLoft(
        [curve_a, curve_b], rg.Point3d.Unset, rg.Point3d.Unset, loft_type, False
    )
    if not breps:
        raise ValueError("Loft failed.")
    return breps[0]


def _cap(curves, tolerance):
    """Join curves into a closed loop and fill it (planar if possible, else a patch)."""
    joined = rg.Curve.JoinCurves(curves, tolerance)
    if not joined:
        raise ValueError("Could not join cap curves.")
    loop = joined[0]
    planar = rg.Brep.CreatePlanarBreps(loop, tolerance)
    if planar:
        return planar[0]
    patch = rg.Brep.CreatePatch([loop], 10, 10, tolerance)
    if patch is None:
        raise ValueError("Could not fill cap curve.")
    return patch


def _ridge_brep(curve, heights, offset_left, offset_right, count, crest_width,
                continuity, tolerance):
    """
    Shared builder for the two curve functions.

    curve        : Rhino.Geometry.Curve -- pouring path (in World XY)
    heights      : list of float -- height per pour point (last value repeats)
    offset_left  : float -- base offset distance on the positive side
    offset_right : float -- base offset distance on the negative side
    """
    if curve is None:
        raise ValueError("curve must be provided.")
    if not heights:
        raise ValueError("At least one height must be given.")

    # Divide the curve into pour points and lift each one to its cone tip.
    params = curve.DivideByCount(int(count), True)
    tips = []
    for i, t in enumerate(params):
        point = curve.PointAt(t)
        h = heights[min(i, len(heights) - 1)]
        tips.append(rg.Point3d(point.X, point.Y, point.Z + h))

    # Crest: a curve through the tips, widened slightly so it can be capped.
    crest = rg.Curve.CreateInterpolatedCurve(tips, 3, rg.CurveKnotStyle.Chord)
    top_a = _offset_curve(crest, crest_width, tolerance)
    top_b = _offset_curve(crest, -crest_width, tolerance)

    # Base: the pouring curve offset to both sides.
    base_a = _offset_curve(curve, offset_left, tolerance)
    base_b = _offset_curve(curve, -offset_right, tolerance)

    # Rounded ends: blend the two sides together at the end and the start.
    base_end = _blend(base_a, _flipped(base_b), continuity)
    base_start = _blend(_flipped(base_a), base_b, continuity)
    top_end = _blend(top_a, _flipped(top_b), continuity)
    top_start = _blend(_flipped(top_a), top_b, continuity)

    parts = [
        _loft(base_a, top_a),                                  # side A
        _loft(base_b, top_b),                                  # side B
        _loft(base_end, top_end, rg.LoftType.Straight),        # end face
        _loft(base_start, top_start, rg.LoftType.Straight),    # start face
        _cap([base_end, base_start, base_a, base_b], tolerance),  # bottom
        _cap([top_end, top_start, top_a, top_b], tolerance),      # crest
    ]
    return list(rg.Brep.JoinBreps(parts, tolerance))


# ---------------------------------------------------------------------------
# 1. ridge along a curve
# ---------------------------------------------------------------------------


def sand_ridge_along_curve(
    curve,
    radius=19.0,
    height=25.0,
    count=10,
    crest_width=0.1,
    continuity=1,
    tolerance=0.001,
):
    """
    Build a sand ridge poured along a curve.

    curve       : Rhino.Geometry.Curve -- pouring path, lying in World XY
    radius      : float -- base half-width (offset to each side of the curve)
    height      : float -- height of the ridge above the curve
    count       : int   -- number of segments the curve is divided into
    crest_width : float -- half-width of the flat crest along the top
    continuity  : int   -- end blend continuity: 0 position, 1 tangency, 2 curvature
    tolerance   : float -- model tolerance for offsets and joins

    Returns a list of Rhino.Geometry.Brep (one closed Brep when the join succeeds).
    """
    return _ridge_brep(
        curve, [height], radius, radius, count, crest_width, continuity, tolerance
    )


# ---------------------------------------------------------------------------
# 2. ridge along a curve with varying widths / heights
# ---------------------------------------------------------------------------


def sand_ridge_along_curve_variable(
    curve,
    radii=None,
    heights=None,
    count=10,
    crest_width=0.1,
    continuity=1,
    tolerance=0.001,
):
    """
    Build several sand ridges along the same curve, one per (radius, height) pair.

    Each radius is used for both the left and the right side of its ridge, so
    radii [27, 18] with heights [22, 15] give a wide, tall ridge (r 27, h 22)
    and a narrower, lower one (r 18, h 15) poured along the same path.

    curve       : Rhino.Geometry.Curve -- pouring path, lying in World XY
    radii       : list of float -- base half-width of each ridge. Default [27, 18].
    heights     : list of float -- height of each ridge. Default [22, 15].
                  If radii and heights have different lengths, the last value of
                  the shorter list is repeated (Grasshopper "longest list").
    count       : int   -- number of segments the curve is divided into
    crest_width : float -- half-width of the crest along the top
    continuity  : int   -- end blend continuity: 0 position, 1 tangency, 2 curvature
    tolerance   : float -- model tolerance for offsets and joins

    Returns a list of Rhino.Geometry.Brep, one ridge per pair.
    """
    if radii is None:
        radii = [27.0, 18.0]
    if heights is None:
        heights = [22.0, 15.0]
    if not isinstance(radii, (list, tuple)):
        radii = [radii]
    if not isinstance(heights, (list, tuple)):
        heights = [heights]
    if not radii or not heights:
        raise ValueError("radii and heights must not be empty.")

    ridges = []
    for i in range(max(len(radii), len(heights))):
        radius = float(radii[min(i, len(radii) - 1)])
        height = float(heights[min(i, len(heights) - 1)])
        ridges.extend(
            _ridge_brep(
                curve, [height], radius, radius, count, crest_width, continuity,
                tolerance,
            )
        )
    return ridges


# ---------------------------------------------------------------------------
# 3. cones at points
# ---------------------------------------------------------------------------


def sand_cones_at_points(points, volumes, slope_angle=34.0, tolerance=0.001):
    """
    Pour a sand cone of a given volume at each point and union overlapping cones.

    points      : list of Rhino.Geometry.Point3d -- cone locations (Z is ignored,
                  every cone base sits on World XY at Z = 0)
    volumes     : list of float -- positive cone volume per point (model units cubed)
    slope_angle : float -- angle of repose of the sand, in degrees above horizontal
    tolerance   : float -- tolerance for the boolean union

    Returns a tuple (cones, breps, status):
        cones  : list of Rhino.Geometry.Brep -- individual capped cones
        breps  : list of Rhino.Geometry.Brep -- unioned result (the cones if the
                 union fails)
        status : str -- description of the union result
    """
    points = list(points or [])
    volumes = list(volumes or [])
    if len(points) != len(volumes):
        raise ValueError("points and volumes must have the same number of items.")

    slope = math.tan(math.radians(slope_angle))
    down = rg.Vector3d(0.0, 0.0, -1.0)

    cones = []
    for index, (point, volume) in enumerate(zip(points, volumes)):
        volume = float(volume)
        if not math.isfinite(volume) or volume <= 0.0:
            raise ValueError(
                "Volume at index {} must be positive and finite.".format(index)
            )

        # V = pi * r^2 * h / 3 with r = h / tan(slope)  ->  solve for h
        height = (3.0 * volume * slope * slope / math.pi) ** (1.0 / 3.0)
        radius = height / slope
        apex = rg.Point3d(point.X, point.Y, height)
        cone = rg.Cone(rg.Plane(apex, down), height, radius)
        if not cone.IsValid:
            raise ValueError("Could not create a valid cone for point {}.".format(index))
        cones.append(cone.ToBrep(True))

    union = rg.Brep.CreateBooleanUnion(cones, tolerance) if cones else None
    breps = [b for b in union if b is not None] if union else []

    if breps:
        status = "Solid union succeeded: {} Brep(s) from {} cone(s).".format(
            len(breps), len(cones)
        )
    elif cones:
        breps = cones
        status = "Warning: solid union failed; returning the {} cone(s).".format(
            len(cones)
        )
    else:
        status = "No cones to union."

    return cones, breps, status


"""
Material processes -- DRY SAND, physically based.

The rules and literature behind every function are documented in
assignments/assignment-03_sand_model_rules.txt (rule numbers in brackets).

The file has two parts:

PART 1  PHYSICAL BEHAVIOUR
    1.1  SandMaterial ............ material values of dry quartz sand
    1.2  contacts ................ Hertz-Mindlin contact, friction, rolling
    1.3  PourEmitter ............. outlet with drop height + outlet diameter,
                                   flow rate from the Beverloo law, can move
                                   along a path
    1.4  ParticleSystem / Simulation  the grain simulation (DEM)
    1.5  analyse_pile ............ angle, height, tip rounding, tail, ...
    1.6  SandLaw ................. the link between grains and geometry:
                                   angle of repose, impact speed and landing
                                   spread as functions of drop height,
                                   outlet diameter and flow rate. Calibrated
                                   from grain simulations. (still need to be done)
    1.7  SandField ............... fast sand-surface model (height field):
                                   sand is deposited where the stream lands
                                   and slides until no slope is steeper than
                                   the SandLaw angle. Works for any source
                                   layout and on top of any terrain.

PART 2  BUILDING AND MODELING
    Every builder takes Rhino geometry in model units, converts to metres,
    runs Part 1 and returns Rhino geometry:
      * sand_pile_at_points ........ fast, SandField
      * sand_ridge_along_curve_physical  fast, SandField, moving outlet
      * sand_on_mesh ............... fast, pour onto existing geometry
      * grain_pour_at_points ....... full grain simulation (slow, exact)
      * grain_pour_along_curve ..... full grain simulation, moving outlet
      * gh_pour .................... grain simulation driven by a GH Timer

Why two levels?
    The grain simulation (DEM) obeys the physics directly, but is slow
    (minutes for one pile). The SandField is fast enough for design, and it
    obeys the same physical laws because every number it uses (angle of
    repose, landing spread, flow rate, impact speed) comes from Part 1 --
    either directly (fall with air drag, Beverloo) or from a SandLaw that
    was calibrated with grain simulations (SandLaw.from_study).

Units: Part 1 works in SI units (m, kg, s). Part 2 converts from the Rhino
model units automatically.
"""

import math
from dataclasses import dataclass

import numpy as np

try:  # Part 2 needs Rhino; Part 1 also works without it
    import Rhino
    import Rhino.Geometry as rg
    import scriptcontext as sc

    HAS_RHINO = True
except ImportError:  # plain Python (tests, parameter studies)
    HAS_RHINO = False


# ============================================================================
# PART 1.1  MATERIAL (rules 2.1, 2.8)
# ============================================================================

@dataclass
class SandMaterial:
    """
    Dry sand, modelled as soft spheres with rolling resistance.

    density          : grain (solid) density, quartz 2650 kg/m^3
    youngs_modulus   : reduced Young's modulus in Pa. Real quartz is ~7e10 Pa,
                       which would need a tiny time step. The angle of repose
                       is insensitive to E (Zhou et al. 2001), so 1e7 is used.
    poisson_ratio    : 0.25
    restitution      : coefficient of restitution e (0 < e < 1), 0.3 - 0.5
    friction         : sliding (Coulomb) friction grain-grain, mu_s ~ 0.5
    rolling_friction : rolling resistance mu_r, replaces grain angularity,
                       0.1 - 0.3, calibrate so a slow pile reaches ~34 deg
    rolling_damping  : viscous part of the rolling model (eta_r, 0 - 1)
    wall_friction    : sliding friction grain-ground/wall (rough ground)
    wall_rolling_friction : rolling friction grain-ground/wall
    radius           : median radius of a MODEL particle (coarse grained)
    radius_spread    : lognormal sigma of the radius distribution (0 = uniform)
    real_grain_diameter : d50 of the real sand, used for air drag so a
                       coarse particle falls through the air like a real grain
    air_density, air_viscosity : 1.2 kg/m^3, 1.8e-5 Pa s
    gravity          : 9.81 m/s^2
    """

    density: float = 2650.0
    youngs_modulus: float = 1.0e7
    poisson_ratio: float = 0.25
    restitution: float = 0.4
    friction: float = 0.5
    rolling_friction: float = 0.2
    rolling_damping: float = 0.3
    wall_friction: float = 0.7
    wall_rolling_friction: float = 0.3
    radius: float = 0.002
    radius_spread: float = 0.15
    real_grain_diameter: float = 0.0003
    air_density: float = 1.2
    air_viscosity: float = 1.8e-5
    gravity: float = 9.81

    # ------------------------------------------------------------------
    # derived contact constants (identical material on both sides)
    # ------------------------------------------------------------------

    @property
    def shear_modulus(self):
        """G = E / (2 (1 + nu))"""
        return self.youngs_modulus / (2.0 * (1.0 + self.poisson_ratio))

    @property
    def effective_youngs(self):
        """E* = E / (2 (1 - nu^2)) for two bodies of the same material."""
        return self.youngs_modulus / (2.0 * (1.0 - self.poisson_ratio ** 2))

    @property
    def effective_shear(self):
        """G* = G / (2 (2 - nu)) for two bodies of the same material."""
        return self.shear_modulus / (2.0 * (2.0 - self.poisson_ratio))

    @property
    def damping_beta(self):
        """beta = ln(e) / sqrt(ln(e)^2 + pi^2)  (negative number)."""
        e = min(max(self.restitution, 1e-6), 0.999999)
        log_e = math.log(e)
        return log_e / math.sqrt(log_e * log_e + math.pi * math.pi)

    def rayleigh_time(self, radius=None):
        """
        Rayleigh time of the smallest particle -- the time a surface wave
        needs to cross a grain. DEM time steps must be a fraction of it.
        """
        r = self.radius if radius is None else radius
        return (
            math.pi * r * math.sqrt(self.density / self.shear_modulus)
            / (0.1631 * self.poisson_ratio + 0.8766)
        )

    def time_step(self, min_radius=None, fraction=0.2):
        """Stable time step dt = fraction * T_Rayleigh(min radius)."""
        if min_radius is None:
            min_radius = self.radius * 0.6
        return fraction * self.rayleigh_time(min_radius)

    def mass(self, radius):
        return self.density * 4.0 / 3.0 * math.pi * radius ** 3

    def terminal_velocity(self, diameter=None, iterations=60):
        """
        Terminal fall velocity of one real grain in air (Schiller-Naumann
        drag). 0.3 mm quartz -> about 2.3 m/s.
        """
        d = self.real_grain_diameter if diameter is None else diameter
        v = 1.0
        for _ in range(iterations):
            re = max(self.air_density * v * d / self.air_viscosity, 1e-9)
            cd = 24.0 / re * (1.0 + 0.15 * re ** 0.687)
            v_new = math.sqrt(
                4.0 * self.gravity * d * self.density / (3.0 * cd * self.air_density)
            )
            v = 0.5 * (v + v_new)
        return v


# ============================================================================
# PART 1.2  CONTACT DETECTION AND CONTACT LAWS (rules 2.2 - 2.4)
# ============================================================================

_PAIR_KEY_BASE = np.int64(1) << np.int64(31)

# the 13 "forward" neighbour cells; together with the own cell every pair of
# neighbouring cells is visited exactly once
_HALF_OFFSETS = np.array(
    [
        (ox, oy, oz)
        for ox in (-1, 0, 1)
        for oy in (-1, 0, 1)
        for oz in (-1, 0, 1)
        if (ox, oy, oz) > (0, 0, 0)
    ],
    dtype=np.int64,
)


# ---------------------------------------------------------------------------
# neighbour search (uniform cell grid, cell size >= largest diameter)
# ---------------------------------------------------------------------------


def _pairs_between(sorted_hash, starts_lookup_hash, members):
    """
    For every particle position p in `members` (index into the sorted list)
    return all sorted positions q whose hash equals starts_lookup_hash[p].
    """
    lo = np.searchsorted(sorted_hash, starts_lookup_hash, side="left")
    hi = np.searchsorted(sorted_hash, starts_lookup_hash, side="right")
    counts = hi - lo
    total = int(counts.sum())
    if total == 0:
        empty = np.empty(0, dtype=np.int64)
        return empty, empty
    first = np.repeat(members, counts)
    run_start = np.repeat(np.cumsum(counts) - counts, counts)
    second = np.repeat(lo, counts) + (np.arange(total) - run_start)
    return first, second


def find_contacts(x, radius, cell_size=None, margin=0.0):
    """
    Find all overlapping sphere pairs.

    x       : (N, 3) positions
    radius  : (N,)   radii
    margin  : extra search distance (> 0 builds a Verlet candidate list
              that stays valid until a grain has moved margin / 2)
    Returns (i, j) index arrays with i < j and |x_i - x_j| < r_i + r_j + margin.
    """
    n = len(x)
    empty = np.empty(0, dtype=np.int64)
    if n < 2:
        return empty, empty
    if cell_size is None:
        cell_size = (2.0 * float(radius.max()) + margin) * 1.0001

    cell = np.floor((x - x.min(axis=0)) / cell_size).astype(np.int64) + 1
    dims = cell.max(axis=0) + 2
    flat = cell[:, 0] + dims[0] * (cell[:, 1] + dims[1] * cell[:, 2])

    order = np.argsort(flat, kind="stable")
    sorted_hash = flat[order]
    positions = np.arange(n, dtype=np.int64)

    firsts, seconds = [], []

    # same cell: keep each unordered pair once
    a, b = _pairs_between(sorted_hash, sorted_hash, positions)
    keep = a < b
    firsts.append(a[keep])
    seconds.append(b[keep])

    # forward neighbour cells
    for ox, oy, oz in _HALF_OFFSETS:
        offset = ox + dims[0] * (oy + dims[1] * oz)
        a, b = _pairs_between(sorted_hash, sorted_hash + offset, positions)
        firsts.append(a)
        seconds.append(b)

    a = order[np.concatenate(firsts)]
    b = order[np.concatenate(seconds)]
    if len(a) == 0:
        return empty, empty

    d = x[b] - x[a]
    reach = radius[a] + radius[b] + margin
    touching = np.einsum("ij,ij->i", d, d) < reach * reach
    a, b = a[touching], b[touching]
    return np.minimum(a, b), np.maximum(a, b)


def pair_keys(i, j):
    """Unique int64 key per particle pair, used for the contact memory."""
    return i.astype(np.int64) * _PAIR_KEY_BASE + j.astype(np.int64)


def lookup_history(old_keys, old_values, new_keys):
    """
    Return the stored vectors of contacts that already existed in the last
    step and zeros for new contacts. old_keys must be sorted.
    """
    out = np.zeros((len(new_keys), 3))
    if len(old_keys) == 0 or len(new_keys) == 0:
        return out
    idx = np.searchsorted(old_keys, new_keys)
    idx_clip = np.minimum(idx, len(old_keys) - 1)
    found = old_keys[idx_clip] == new_keys
    out[found] = old_values[idx_clip[found]]
    return out


# ---------------------------------------------------------------------------
# contact law
# ---------------------------------------------------------------------------


def _dot(a, b):
    return np.einsum("ij,ij->i", a, b)


def _rotate_into_plane(vec, n):
    """Project memory vectors onto the current tangent plane, keep length."""
    length = np.linalg.norm(vec, axis=1)
    projected = vec - _dot(vec, n)[:, None] * n
    p_length = np.linalg.norm(projected, axis=1)
    scale = np.where(p_length > 1e-30, length / np.maximum(p_length, 1e-30), 0.0)
    return projected * scale[:, None]


def contact_law(
    material,
    dt,
    n,
    delta,
    v_c,
    w_rel,
    r_eff,
    m_eff,
    i_roll,
    xi_old,
    roll_old,
    friction,
    rolling_friction,
):
    """
    Hertz-Mindlin contact with Coulomb friction and rolling resistance.

    material         : SandMaterial
    dt               : time step
    n, delta, v_c, w_rel : see module docstring, shapes (K,3)/(K,)
    r_eff            : (K,) effective radius R* = R_i R_j / (R_i + R_j)
    m_eff            : (K,) effective mass m* = m_i m_j / (m_i + m_j)
    i_roll           : (K,) effective rolling inertia
    xi_old           : (K,3) tangential spring stretch from the last step
    roll_old         : (K,3) rolling spring torque from the last step
    friction         : sliding friction coefficient (scalar)
    rolling_friction : rolling friction coefficient (scalar)

    Returns (force_on_j, tangential_force_on_j, roll_torque_on_i,
             xi_new, roll_new, normal_force_magnitude)
    """
    e_star = material.effective_youngs
    g_star = material.effective_shear
    beta = material.damping_beta
    root_56 = math.sqrt(5.0 / 6.0)

    sqrt_rd = np.sqrt(r_eff * delta)
    s_n = 2.0 * e_star * sqrt_rd                    # normal stiffness
    s_t = 8.0 * g_star * sqrt_rd                    # tangential stiffness

    # --- normal: Hertz spring + damper, no attraction (dry sand) ---------
    v_n = _dot(v_c, n)
    c_n = -2.0 * root_56 * beta * np.sqrt(s_n * m_eff)
    f_n = 4.0 / 3.0 * e_star * np.sqrt(r_eff) * delta ** 1.5 - c_n * v_n
    f_n = np.maximum(f_n, 0.0)

    # --- tangential: Mindlin spring with memory + Coulomb ----------------
    v_t = v_c - v_n[:, None] * n
    xi = _rotate_into_plane(xi_old, n) + v_t * dt
    c_t = -2.0 * root_56 * beta * np.sqrt(s_t * m_eff)
    f_t = -s_t[:, None] * xi - c_t[:, None] * v_t
    f_t_len = np.linalg.norm(f_t, axis=1)
    limit = friction * f_n
    sliding = f_t_len > limit
    if np.any(sliding):
        scale = limit[sliding] / np.maximum(f_t_len[sliding], 1e-30)
        f_t[sliding] *= scale[:, None]
        xi[sliding] = -f_t[sliding] / np.maximum(s_t[sliding], 1e-30)[:, None]

    # --- rolling resistance (elastic-plastic spring-dashpot) -------------
    w_roll = w_rel - _dot(w_rel, n)[:, None] * n        # drop twisting part
    k_r = 2.25 * s_n * rolling_friction ** 2 * r_eff ** 2
    m_spring = _rotate_into_plane(roll_old, n) - k_r[:, None] * w_roll * dt
    m_limit = rolling_friction * r_eff * f_n
    m_len = np.linalg.norm(m_spring, axis=1)
    full = m_len >= m_limit
    if np.any(full):
        scale = m_limit[full] / np.maximum(m_len[full], 1e-30)
        m_spring[full] *= scale[:, None]
    c_r = material.rolling_damping * 2.0 * np.sqrt(i_roll * k_r)
    m_damp = np.where(full[:, None], 0.0, -c_r[:, None] * w_roll)
    roll_torque_i = m_spring + m_damp

    force_j = f_n[:, None] * n + f_t
    return force_j, f_t, roll_torque_i, xi, m_spring, f_n


# ============================================================================
# PART 1.3  POUR SOURCES (rules 2.7, 3.7, 4.1, 4.3, 4.4)
# ============================================================================

def beverloo_flow_rate(outlet_diameter, grain_diameter, bulk_density=1600.0,
                       c=0.58, k=2.9, gravity=9.81, slit=False):
    """
    Mass flow rate out of a funnel/hopper (Beverloo law, rule 3.7).

        W = C rho_b sqrt(g) (D - k d)^(5/2)       round outlet
        W = C rho_b sqrt(g) (D - k d)^(3/2)       slit (per metre length)

    outlet_diameter : D [m]
    grain_diameter  : d [m]  (k ~ 2.9 reported for sand)
    Returns kg/s (0 if the outlet is too small and jams).
    """
    effective = outlet_diameter - k * grain_diameter
    if effective <= 0.0:
        return 0.0
    exponent = 1.5 if slit else 2.5
    return c * bulk_density * math.sqrt(gravity) * effective ** exponent


def sample_radii(material, count, rng):
    """Lognormal radii around material.radius, clipped to [0.6, 1.6] x median."""
    if material.radius_spread <= 0.0:
        return np.full(count, material.radius)
    r = material.radius * np.exp(rng.normal(0.0, material.radius_spread, count))
    return np.clip(r, 0.6 * material.radius, 1.6 * material.radius)


class PourEmitter:
    """
    Sand falling out of a round outlet (funnel / nozzle).

    position        : (x, y) of the outlet axis [m]
    drop_height     : height of the outlet above the ground [m]
                      (with follow_pile: above the pile top)
    outlet_diameter : diameter of the outlet = width of the stream [m].
                      Must be at least ~3 model grain diameters, otherwise
                      the model particles jam at the outlet.
    flow_rate       : mass flow rate Q [kg/s]. None (default) = computed
                      from the outlet diameter with the Beverloo law using
                      the REAL grain diameter (rule 3.7), so changing the
                      outlet changes the flow like a real funnel.
    total_mass      : sand to pour in total [kg]
    exit_speed      : downward speed when leaving the outlet [m/s]
    spread_speed    : random sideways speed (stream widening) [m/s]
    max_grains      : safety limit on the number of particles
    follow_pile     : keep drop_height ABOVE THE PILE TOP (constant fall
                      distance while the pile grows; avoids burying the outlet)
    path            : optional list of (x, y) points; the outlet then moves
                      along this polyline with outlet_speed [m/s] and stops
                      pouring at the end of the path
    """

    def __init__(self, position=(0.0, 0.0), drop_height=0.1, outlet_diameter=0.03,
                 flow_rate=None, total_mass=0.1, exit_speed=0.5,
                 spread_speed=0.02, max_grains=20000, follow_pile=False,
                 path=None, outlet_speed=0.05, material=None):
        self.position = (float(position[0]), float(position[1]))
        self.drop_height = float(drop_height)
        self.outlet_diameter = float(outlet_diameter)
        if flow_rate is None:
            mat = material or SandMaterial()
            flow_rate = beverloo_flow_rate(self.outlet_diameter, mat.real_grain_diameter,
                                           gravity=mat.gravity)
        self.flow_rate = float(flow_rate)
        self.total_mass = float(total_mass)
        self.exit_speed = float(exit_speed)
        self.spread_speed = float(spread_speed)
        self.max_grains = int(max_grains)
        self.follow_pile = bool(follow_pile)

        self.path = None if path is None else np.asarray(path, float)[:, :2]
        self.outlet_speed = float(outlet_speed)
        if self.path is not None:
            seg = np.linalg.norm(np.diff(self.path, axis=0), axis=1)
            self._path_cum = np.concatenate([[0.0], np.cumsum(seg)])
            self.position = tuple(self.path[0])

        self.emitted_mass = 0.0
        self.emitted_count = 0
        self.blocked_steps = 0
        self.first_emit_time = None
        self.last_emit_time = None
        self._budget = 0.0
        self._next_radius = None
        self._path_done = False
        self._start_time = None

    def _update_position(self, time):
        if self.path is None:
            return
        if self._start_time is None:
            self._start_time = time
        s = (time - self._start_time) * self.outlet_speed
        if s >= self._path_cum[-1]:
            self._path_done = True
            s = self._path_cum[-1]
        self.position = (
            float(np.interp(s, self._path_cum, self.path[:, 0])),
            float(np.interp(s, self._path_cum, self.path[:, 1])),
        )

    @property
    def finished(self):
        return (
            self.emitted_mass >= self.total_mass
            or self.emitted_count >= self.max_grains
            or self._path_done
        )

    def outlet_height(self, system):
        if not self.follow_pile or system.count == 0:
            return self.drop_height
        resting = system.contact_count > 0
        top = float((system.x[resting, 2] + system.r[resting]).max()) if resting.any() else 0.0
        return top + self.drop_height

    def grains_per_second(self, material):
        """
        Impact frequency f (rule 4.2): the rate actually achieved if grains
        were released, otherwise the nominal Q / m_grain.
        """
        if self.emitted_count > 1 and self.last_emit_time > self.first_emit_time:
            return (self.emitted_count - 1) / (self.last_emit_time - self.first_emit_time)
        return self.flow_rate / material.mass(material.radius)

    def actual_flow_rate(self):
        """Mass flow rate actually released (lower than Q if the nozzle clogs)."""
        if self.emitted_count > 1 and self.last_emit_time > self.first_emit_time:
            return self.emitted_mass / (self.last_emit_time - self.first_emit_time)
        return self.flow_rate

    def emit(self, system, rng):
        """Release the grains that the flow rate allows in this time step."""
        if self.finished:
            return 0
        mat = system.material
        self._update_position(system.time)
        if self.finished:
            return 0
        self._budget += self.flow_rate * system.dt
        z0 = self.outlet_height(system)
        r_nozzle = 0.5 * self.outlet_diameter

        # grains near the nozzle, to avoid creating overlaps
        if system.count:
            near = np.abs(system.x[:, 2] - z0) < 10.0 * mat.radius
            near_x = system.x[near]
            near_r = system.r[near]
        else:
            near_x = np.zeros((0, 3))
            near_r = np.zeros(0)

        new_x, new_r = [], []
        released = 0
        while not self.finished:
            if self._next_radius is None:
                self._next_radius = float(sample_radii(mat, 1, rng)[0])
            radius = self._next_radius
            mass = mat.mass(radius)
            if self._budget < mass:
                break

            placed = False
            limit = max(r_nozzle - radius, 0.0)
            for _ in range(8):
                rho = limit * math.sqrt(rng.random())
                phi = 2.0 * math.pi * rng.random()
                p = np.array([
                    self.position[0] + rho * math.cos(phi),
                    self.position[1] + rho * math.sin(phi),
                    z0 + radius * (1.0 + 6.0 * rng.random()),
                ])
                ok = True
                if len(near_r):
                    gap = np.linalg.norm(near_x - p, axis=1) - near_r - radius
                    ok = bool((gap > 0.0).all())
                if ok and new_r:
                    gap = np.linalg.norm(np.array(new_x) - p, axis=1) - np.array(new_r) - radius
                    ok = bool((gap > 0.0).all())
                if ok:
                    placed = True
                    break
            if not placed:
                # nozzle is full: the stream is denser than the grains can
                # fall away -> try again next step
                self.blocked_steps += 1
                break

            new_x.append(p)
            new_r.append(radius)
            self._budget -= mass
            self.emitted_mass += mass
            self.emitted_count += 1
            self._next_radius = None
            released += 1

        if new_r:
            k = len(new_r)
            vel = np.zeros((k, 3))
            vel[:, :2] = rng.normal(0.0, self.spread_speed, (k, 2))
            vel[:, 2] = -self.exit_speed
            system.add_particles(np.array(new_x), np.array(new_r), vel)
            if self.first_emit_time is None:
                self.first_emit_time = system.time
            self.last_emit_time = system.time
        return released


# ============================================================================
# PART 1.4  PARTICLE SYSTEM AND TIME INTEGRATION (rules 2.1, 2.5, 2.6, 4.2)
# ============================================================================

def _cross(a, b):
    return np.cross(a, b)


class ParticleSystem:
    """
    All grains plus the walls they can touch.

    material : SandMaterial
    planes   : list of (point, normal) tuples. The normal points into the
               region where grains are allowed. A ground plane z = 0 is
               added automatically unless ground=False.
    """

    def __init__(self, material=None, planes=None, ground=True, drag=True):
        self.material = material or SandMaterial()
        self.drag = drag
        self.time = 0.0
        self.dt = self.material.time_step()

        walls = []
        if ground:
            walls.append(((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
        walls.extend(planes or [])
        self.plane_points = np.array([w[0] for w in walls], dtype=float).reshape(-1, 3)
        normals = np.array([w[1] for w in walls], dtype=float).reshape(-1, 3)
        lengths = np.linalg.norm(normals, axis=1)
        self.plane_normals = normals / np.where(lengths > 0, lengths, 1.0)[:, None]

        self.x = np.zeros((0, 3))
        self.v = np.zeros((0, 3))
        self.w = np.zeros((0, 3))
        self.r = np.zeros(0)
        self.m = np.zeros(0)
        self.inertia = np.zeros(0)
        self._acc = np.zeros((0, 3))
        self._ang_acc = np.zeros((0, 3))

        # bookkeeping per grain
        self.born_time = np.zeros(0)
        self.first_contact_time = np.zeros(0)
        self.impact_speed = np.zeros(0)
        self.settled_time = np.zeros(0)

        # contact memory
        self._pair_keys = np.zeros(0, dtype=np.int64)
        self._pair_xi = np.zeros((0, 3))
        self._pair_roll = np.zeros((0, 3))
        n_planes = len(self.plane_points)
        self._wall_xi = np.zeros((0, n_planes, 3))
        self._wall_roll = np.zeros((0, n_planes, 3))

        self.contact_count = np.zeros(0, dtype=np.int64)
        self.pair_count = 0

        # Verlet candidate list: rebuilt only when a grain moved > margin/2
        self.verlet_margin = 0.4 * self.material.radius
        self._cand_i = np.zeros(0, dtype=np.int64)
        self._cand_j = np.zeros(0, dtype=np.int64)
        self._x_ref = np.zeros((0, 3))
        self.rebuilds = 0

    # ------------------------------------------------------------------
    # particles
    # ------------------------------------------------------------------

    @property
    def count(self):
        return len(self.r)

    def add_particles(self, positions, radii, velocities=None):
        positions = np.asarray(positions, dtype=float).reshape(-1, 3)
        radii = np.asarray(radii, dtype=float).reshape(-1)
        k = len(radii)
        if k == 0:
            return
        if velocities is None:
            velocities = np.zeros((k, 3))
        velocities = np.asarray(velocities, dtype=float).reshape(-1, 3)
        mass = self.material.density * 4.0 / 3.0 * math.pi * radii ** 3
        n_planes = len(self.plane_points)

        self.x = np.vstack([self.x, positions])
        self.v = np.vstack([self.v, velocities])
        self.w = np.vstack([self.w, np.zeros((k, 3))])
        self.r = np.concatenate([self.r, radii])
        self.m = np.concatenate([self.m, mass])
        self.inertia = np.concatenate([self.inertia, 0.4 * mass * radii ** 2])
        g = np.array([0.0, 0.0, -self.material.gravity])
        self._acc = np.vstack([self._acc, np.tile(g, (k, 1))])
        self._ang_acc = np.vstack([self._ang_acc, np.zeros((k, 3))])
        self.born_time = np.concatenate([self.born_time, np.full(k, self.time)])
        self.first_contact_time = np.concatenate([self.first_contact_time, np.full(k, np.nan)])
        self.impact_speed = np.concatenate([self.impact_speed, np.full(k, np.nan)])
        self.settled_time = np.concatenate([self.settled_time, np.full(k, np.nan)])
        self._wall_xi = np.concatenate([self._wall_xi, np.zeros((k, n_planes, 3))])
        self._wall_roll = np.concatenate([self._wall_roll, np.zeros((k, n_planes, 3))])
        self.contact_count = np.concatenate([self.contact_count, np.zeros(k, dtype=np.int64)])

        # a smaller grain may need a smaller time step
        self.dt = min(self.dt, self.material.time_step(float(radii.min())))

    def speed(self):
        return np.linalg.norm(self.v, axis=1)

    def kinetic_energy(self):
        trans = 0.5 * self.m * np.einsum("ij,ij->i", self.v, self.v)
        rot = 0.5 * self.inertia * np.einsum("ij,ij->i", self.w, self.w)
        return float(trans.sum() + rot.sum())

    def settle_speed(self):
        """Speed below which a grain counts as 'at rest'."""
        return 0.02 * math.sqrt(self.material.gravity * self.material.radius)

    # ------------------------------------------------------------------
    # forces
    # ------------------------------------------------------------------

    def _drag_acceleration(self):
        """
        Air drag (rule 2.6). The acceleration is computed for a REAL grain
        of diameter real_grain_diameter * (r / r_median), so a coarse model
        particle falls through the air like real sand does.
        """
        mat = self.material
        speed = self.speed()
        d = mat.real_grain_diameter * self.r / mat.radius
        re = np.maximum(mat.air_density * speed * d / mat.air_viscosity, 1e-12)
        cd = 24.0 / re * (1.0 + 0.15 * np.minimum(re, 1000.0) ** 0.687)
        cd = np.where(re > 1000.0, 0.44, cd)
        factor = 3.0 * mat.air_density * cd * speed / (4.0 * mat.density * d)
        return -factor[:, None] * self.v

    def _overlapping_pairs(self):
        if len(self._x_ref) != self.count or (
            float(np.abs(self.x - self._x_ref).max()) > 0.5 * self.verlet_margin
        ):
            self._cand_i, self._cand_j = find_contacts(
                self.x, self.r, margin=self.verlet_margin
            )
            self._x_ref = self.x.copy()
            self.rebuilds += 1
        i, j = self._cand_i, self._cand_j
        d = self.x[j] - self.x[i]
        dist = np.sqrt(np.einsum("ij,ij->i", d, d))
        touch = dist < self.r[i] + self.r[j]
        return i[touch], j[touch], d[touch], dist[touch]

    def _compute_accelerations(self):
        mat = self.material
        n = self.count
        force = np.zeros((n, 3))
        torque = np.zeros((n, 3))
        touching = np.zeros(n, dtype=np.int64)

        # ---------------- grain - grain ----------------------------------
        i, j, d, dist = self._overlapping_pairs()
        self.pair_count = len(i)
        if len(i):
            normal = d / np.maximum(dist, 1e-30)[:, None]
            delta = self.r[i] + self.r[j] - dist
            ri, rj = self.r[i], self.r[j]
            lever = ri[:, None] * self.w[i] + rj[:, None] * self.w[j]
            v_c = self.v[j] - self.v[i] - _cross(lever, normal)
            w_rel = self.w[i] - self.w[j]
            r_eff = ri * rj / (ri + rj)
            mi, mj = self.m[i], self.m[j]
            m_eff = mi * mj / (mi + mj)
            ai = self.inertia[i] + mi * ri * ri
            aj = self.inertia[j] + mj * rj * rj
            i_roll = ai * aj / (ai + aj)

            keys = pair_keys(i, j)
            xi_old = lookup_history(self._pair_keys, self._pair_xi, keys)
            roll_old = lookup_history(self._pair_keys, self._pair_roll, keys)

            f_j, f_t, roll_i, xi_new, roll_new, _ = contact_law(
                mat, self.dt, normal, delta, v_c, w_rel, r_eff, m_eff, i_roll,
                xi_old, roll_old, mat.friction, mat.rolling_friction,
            )
            np.add.at(force, j, f_j)
            np.add.at(force, i, -f_j)
            n_x_ft = _cross(normal, f_t)
            np.add.at(torque, i, -ri[:, None] * n_x_ft + roll_i)
            np.add.at(torque, j, -rj[:, None] * n_x_ft - roll_i)
            np.add.at(touching, i, 1)
            np.add.at(touching, j, 1)

            order = np.argsort(keys)
            self._pair_keys = keys[order]
            self._pair_xi = xi_new[order]
            self._pair_roll = roll_new[order]
        else:
            self._pair_keys = np.zeros(0, dtype=np.int64)
            self._pair_xi = np.zeros((0, 3))
            self._pair_roll = np.zeros((0, 3))

        # ---------------- grain - wall -----------------------------------
        for p in range(len(self.plane_points)):
            plane_n = self.plane_normals[p]
            height = (self.x - self.plane_points[p]) @ plane_n
            delta = self.r - height
            hit = np.nonzero(delta > 0.0)[0]
            keep_xi = np.zeros((n, 3))
            keep_roll = np.zeros((n, 3))
            if len(hit):
                k = len(hit)
                normal = np.tile(-plane_n, (k, 1))      # from grain to wall
                ri = self.r[hit]
                v_c = -self.v[hit] - _cross(ri[:, None] * self.w[hit], normal)
                w_rel = self.w[hit]
                mi = self.m[hit]
                i_roll = self.inertia[hit] + mi * ri * ri
                f_wall, f_t, roll_i, xi_new, roll_new, _ = contact_law(
                    mat, self.dt, normal, delta[hit], v_c, w_rel, ri, mi, i_roll,
                    self._wall_xi[hit, p], self._wall_roll[hit, p],
                    mat.wall_friction, mat.wall_rolling_friction,
                )
                force[hit] -= f_wall
                torque[hit] += -ri[:, None] * _cross(normal, f_t) + roll_i
                touching[hit] += 1
                keep_xi[hit] = xi_new
                keep_roll[hit] = roll_new
            self._wall_xi[:, p] = keep_xi
            self._wall_roll[:, p] = keep_roll

        self.contact_count = touching
        acc = force / self.m[:, None]
        acc[:, 2] -= mat.gravity
        if self.drag:
            acc += self._drag_acceleration()
        ang_acc = torque / self.inertia[:, None]
        return acc, ang_acc

    # ------------------------------------------------------------------
    # time integration
    # ------------------------------------------------------------------

    def step(self):
        """One velocity Verlet step (half kick - drift - forces - half kick)."""
        if self.count == 0:
            self.time += self.dt
            return
        dt = self.dt
        self.v += 0.5 * dt * self._acc
        self.w += 0.5 * dt * self._ang_acc
        self.x += dt * self.v
        self._acc, self._ang_acc = self._compute_accelerations()
        self.v += 0.5 * dt * self._acc
        self.w += 0.5 * dt * self._ang_acc
        self.time += dt
        self._bookkeeping()

    def _bookkeeping(self):
        """Record first impact (time, speed) and first time at rest (4.2)."""
        speed = self.speed()
        touching = self.contact_count > 0
        new_impact = touching & np.isnan(self.first_contact_time)
        if np.any(new_impact):
            self.first_contact_time[new_impact] = self.time
            self.impact_speed[new_impact] = speed[new_impact]
        rest = (
            touching
            & ~np.isnan(self.first_contact_time)
            & np.isnan(self.settled_time)
            & (speed < self.settle_speed())
        )
        if np.any(rest):
            self.settled_time[rest] = self.time


class Simulation:
    """
    A particle system plus one or more emitters, advanced in time.

    Typical use (outside or inside Grasshopper):

        sim = Simulation(SandMaterial(), [PourEmitter(height=0.1)])
        sim.run_until_settled(max_time=5.0)
        print(analyse_pile(sim.system))
    """

    def __init__(self, material=None, emitters=None, planes=None, drag=True, seed=1):
        self.system = ParticleSystem(material, planes=planes, drag=drag)
        self.emitters = list(emitters or [])
        self.rng = np.random.default_rng(seed)
        self._quiet_time = 0.0

    @property
    def time(self):
        return self.system.time

    def emitting(self):
        return any(not e.finished for e in self.emitters)

    def advance(self, steps=100):
        sys_ = self.system
        for _ in range(int(steps)):
            for emitter in self.emitters:
                emitter.emit(sys_, self.rng)
            sys_.step()
        if not self.emitting() and sys_.count:
            # 99 % of the grains at rest (a single grain rolling away far
            # from the pile should not keep the simulation running forever)
            if float(np.quantile(sys_.speed(), 0.99)) < sys_.settle_speed():
                self._quiet_time += steps * sys_.dt
            else:
                self._quiet_time = 0.0
        return self

    def is_settled(self, quiet_time=0.05):
        return (
            not self.emitting()
            and self.system.count > 0
            and self._quiet_time >= quiet_time
        )

    def run_until_settled(self, max_time=10.0, chunk=200, callback=None):
        """Run until all sand is poured and at rest, or max_time is reached."""
        while self.time < max_time and not self.is_settled():
            self.advance(chunk)
            if callback is not None:
                callback(self)
        return self


# ============================================================================
# PART 1.5  PILE MEASUREMENT AND PARAMETER STUDIES (rules 3.1, 3.5, 3.6, 5.2)
# ============================================================================

def pile_profile(system, center=None, bin_width=None):
    """
    Radial surface profile of the pile: highest grain top per ring.

    Only grains that touch something are used, so the falling stream is
    ignored. Returns (ring_outer_radii, heights, center_xy).
    """
    mat = system.material
    if bin_width is None:
        bin_width = 2.0 * mat.radius
    on_pile = system.contact_count > 0
    if not np.any(on_pile):
        return np.zeros(0), np.zeros(0), (0.0, 0.0)
    x = system.x[on_pile]
    top = x[:, 2] + system.r[on_pile]
    if center is None:
        weights = system.m[on_pile]
        center = (
            float(np.average(x[:, 0], weights=weights)),
            float(np.average(x[:, 1], weights=weights)),
        )
    dist = np.hypot(x[:, 0] - center[0], x[:, 1] - center[1])
    bins = (dist / bin_width).astype(np.int64)
    heights = np.zeros(int(bins.max()) + 1)
    np.maximum.at(heights, bins, top)
    outer = (np.arange(len(heights)) + 1) * bin_width
    return outer, heights, center


def analyse_pile(system, emitters=None, center=None):
    """
    Measure the pile. Returns a dict with (SI units, angles in degrees):

    height             H, highest point of the pile
    base_radius        radius where the pile is thinner than one grain
    angle              angle of repose, fitted on the flank between 20 % and
                       80 % of the height (excludes top and foot)
    flank_curvature    second derivative of the flank, < 0 means convex
    apex_radius        radius of curvature of the top (small = sharp tip)
    apex_drop          height of the ideal sharp cone tip minus H
                       (how much of the tip is "missing" by rounding)
    tail_length        how far the pile foot runs out beyond the straight
                       cone line
    crater_depth       H minus the height on the axis
    aspect             H / base_radius
    packing_fraction   grain volume / pile volume
    impact_speed       mean speed of grains at first contact
    settle_time        mean time from first contact until at rest
    impact_frequency   grains per second hitting the pile (f = Q / m)
    impact_ratio       Pi = f * settle_time  (<<1 quasi-static, >>1 flowing)
    grains             number of grains
    """
    mat = system.material
    out = {"grains": int(system.count)}
    radii, heights, center = pile_profile(system, center=center)
    if len(heights) < 4:
        out["error"] = "pile too small to analyse"
        return out

    bin_width = radii[0]
    mids = radii - 0.5 * bin_width
    h_max = float(heights.max())
    thin = 2.0 * mat.radius          # thinner than one grain = outside the pile
    above = heights > thin
    base_index = len(heights) - 1
    for k in range(len(heights)):
        if not above[k] and k > 0:
            base_index = k
            break
    base_radius = float(radii[base_index - 1]) if base_index > 0 else float(radii[0])
    out.update(height=h_max, base_radius=base_radius,
               aspect=h_max / max(base_radius, 1e-12), center=center)

    # straight flank fit
    mask = (heights > 0.2 * h_max) & (heights < 0.8 * h_max) & (mids < base_radius)
    if mask.sum() >= 3:
        slope, intercept = np.polyfit(mids[mask], heights[mask], 1)
        out["angle"] = math.degrees(math.atan(-slope))
        if mask.sum() >= 4:
            c2 = np.polyfit(mids[mask], heights[mask], 2)[0]
            out["flank_curvature"] = float(2.0 * c2)
        out["apex_drop"] = float(intercept - h_max)
        if slope < 0:
            foot = intercept / -slope
            out["tail_length"] = float(base_radius - foot)
    else:
        out["angle"] = float("nan")

    # apex: h = H0 - r^2 / (2 rho) on the top 20 %
    top = heights > 0.8 * h_max
    top &= mids < 0.5 * base_radius
    if top.sum() >= 3:
        s, _ = np.polyfit(mids[top] ** 2, heights[top], 1)
        out["apex_radius"] = float(-1.0 / (2.0 * s)) if s < 0 else float("inf")
    else:
        # top is narrower than three rings: as sharp as the grain size allows
        out["apex_radius"] = float(mat.radius)
    out["crater_depth"] = float(h_max - heights[0])

    # packing fraction inside the pile radius
    inner = radii[:base_index] if base_index > 0 else radii[:1]
    rings = math.pi * (inner ** 2 - np.concatenate([[0.0], inner[:-1]]) ** 2)
    pile_volume = float((rings * heights[: len(inner)]).sum())
    dist = np.hypot(system.x[:, 0] - center[0], system.x[:, 1] - center[1])
    inside = (system.contact_count > 0) & (dist < base_radius)
    grain_volume = float((4.0 / 3.0 * math.pi * system.r[inside] ** 3).sum())
    out["packing_fraction"] = grain_volume / pile_volume if pile_volume > 0 else float("nan")

    # impact / settling bookkeeping (rule 4.2)
    hit = ~np.isnan(system.first_contact_time)
    rest = hit & ~np.isnan(system.settled_time)
    out["impact_speed"] = float(np.mean(system.impact_speed[hit])) if hit.any() else float("nan")
    t_s = float(np.mean(system.settled_time[rest] - system.first_contact_time[rest])) if rest.any() else float("nan")
    out["settle_time"] = t_s
    if emitters:
        f = sum(e.grains_per_second(mat) for e in emitters)
        out["impact_frequency"] = f
        out["actual_flow_rate"] = sum(e.actual_flow_rate() for e in emitters)
        out["impact_ratio"] = f * t_s
    return out


def pour_pile(drop_height=0.1, outlet_diameter=0.03, flow_rate=None,
              total_mass=0.05, material=None, max_time=8.0, seed=1,
              callback=None, follow_pile=False):
    """
    Pour one pile from a point source and return (simulation, result dict).
    flow_rate None = Beverloo flow from the outlet diameter.
    """
    material = material or SandMaterial()
    emitter = PourEmitter(
        position=(0.0, 0.0), drop_height=drop_height, outlet_diameter=outlet_diameter,
        flow_rate=flow_rate, total_mass=total_mass, follow_pile=follow_pile,
        material=material,
    )
    sim = Simulation(material, [emitter], seed=seed)
    sim.run_until_settled(max_time=max_time, callback=callback)
    result = analyse_pile(sim.system, [emitter], center=(0.0, 0.0))
    result.update(drop_height=drop_height, flow_rate=emitter.flow_rate,
                  outlet_diameter=outlet_diameter,
                  settled=sim.is_settled(), sim_time=sim.time)
    return sim, result


def parameter_study(drop_heights, outlet_diameters, total_mass=0.05, material=None,
                    max_time=8.0, verbose=True, **kwargs):
    """
    Sweep drop height x outlet diameter (validation plan 5.2). The outlet
    diameter sets the flow rate (Beverloo). Returns one result dict per run.
    Feed the results to SandLaw.from_study() to calibrate the fast model.
    """
    results = []
    for h in drop_heights:
        for d in outlet_diameters:
            _, res = pour_pile(h, d, None, total_mass, material, max_time=max_time, **kwargs)
            results.append(res)
            if verbose:
                print(format_result(res))
    return results


def format_result(res):
    keys = ["drop_height", "outlet_diameter", "flow_rate", "grains", "angle", "height", "base_radius",
            "apex_radius", "apex_drop", "tail_length", "crater_depth",
            "packing_fraction", "impact_speed", "impact_ratio", "actual_flow_rate",
            "settled"]
    parts = []
    for k in keys:
        if k in res:
            v = res[k]
            parts.append("{}={:.4g}".format(k, v) if isinstance(v, float) else "{}={}".format(k, v))
    return ", ".join(parts)


# ============================================================================
# PART 1.6  SANDLAW -- FROM GRAIN PHYSICS TO GEOMETRY RULES (rules 2.6, 3.6, 4.x)
# ============================================================================


def impact_speed(drop_height, material=None, exit_speed=0.5, steps=400):
    """
    Speed of a real grain after falling drop_height metres through air
    (rule 2.6). Integrates  dv/dt = g - drag(v)  for the real grain diameter.
    Above ~0.5-1 m the speed stops growing (terminal velocity ~2.3 m/s for
    0.3 mm sand).
    """
    mat = material or SandMaterial()
    if drop_height <= 0.0:
        return float(exit_speed)
    d = mat.real_grain_diameter
    v = float(exit_speed)
    dz = drop_height / steps
    for _ in range(steps):
        re = max(mat.air_density * v * d / mat.air_viscosity, 1e-12)
        cd = 24.0 / re * (1.0 + 0.15 * min(re, 1000.0) ** 0.687)
        drag = 3.0 * mat.air_density * cd * v * v / (4.0 * mat.density * d)
        # v dv = (g - drag) dz
        v = math.sqrt(max(v * v + 2.0 * (mat.gravity - drag) * dz, 0.0))
    return v


@dataclass
class SandLaw:
    """
    Pile-scale rules used by the fast geometry builders.

    angle(drop_height, flow_rate):
        angle = static_angle
                + impact_coeff * ln(v_impact / v_ref)
                + flow_coeff   * ln(flow_rate / flow_ref)
        clamped to [min_angle, max_angle].
        v_impact comes from impact_speed() (fall with air drag), so the
        drop-height effect saturates at terminal velocity automatically.
        - static_angle 34 deg: literature value for slowly poured dry sand
          (rule 3.1), reached at the reference drop height ref_height.
        - impact_coeff: PRELIMINARY, from two grain simulations
          (3 cm -> 31.6 deg, 30 cm -> 22.4 deg). Re-calibrate with
          SandLaw.from_study().
        - flow_coeff: 0 until a flow-rate study is done (rule 4.1).
        - max_angle 39 deg: angle of maximum stability (crater angle, 3.2).

    landing_radius(drop_height, outlet_diameter):
        r = outlet_diameter / 2 + bounce_factor * (e * v_impact)^2 / g
        (stream width + ballistic jump after impact, rule 3.6). This is
        what rounds the tip of the pile: big r -> round/flat top.

    flow_rate(outlet_diameter): Beverloo law with the real grain size (3.7).
    """

    material: SandMaterial = None
    static_angle: float = 34.0
    ref_height: float = 0.03
    impact_coeff: float = -12.2
    flow_coeff: float = 0.0
    flow_ref: float = 0.05
    min_angle: float = 20.0
    max_angle: float = 39.0
    bounce_factor: float = 1.0
    bulk_density: float = 1600.0
    exit_speed: float = 0.5

    def __post_init__(self):
        if self.material is None:
            self.material = SandMaterial()

    def impact_speed(self, drop_height):
        return impact_speed(drop_height, self.material, self.exit_speed)

    def angle(self, drop_height, flow_rate=None):
        v = self.impact_speed(max(drop_height, 0.0))
        v_ref = self.impact_speed(self.ref_height)
        a = self.static_angle + self.impact_coeff * math.log(max(v, 1e-6) / v_ref)
        if flow_rate is not None and flow_rate > 0.0:
            a += self.flow_coeff * math.log(flow_rate / self.flow_ref)
        return min(max(a, self.min_angle), self.max_angle)

    def landing_radius(self, drop_height, outlet_diameter):
        v = self.impact_speed(max(drop_height, 0.0))
        jump = (self.material.restitution * v) ** 2 / self.material.gravity
        return 0.5 * outlet_diameter + self.bounce_factor * jump

    def flow_rate(self, outlet_diameter):
        return beverloo_flow_rate(
            outlet_diameter, self.material.real_grain_diameter,
            bulk_density=self.bulk_density, gravity=self.material.gravity,
        )

    @classmethod
    def from_study(cls, results, material=None, **kwargs):
        """
        Calibrate the law from a grain parameter study
        (results of parameter_study()). Fits
            angle = a + b ln(v_impact) + c ln(Q)
        """
        law = cls(material=material, **kwargs)
        rows = [r for r in results if math.isfinite(r.get("angle", float("nan")))]
        if len(rows) < 2:
            raise ValueError("need at least 2 valid runs")
        use_flow = len({r["flow_rate"] for r in rows}) > 1 and len(rows) >= 3
        A, y = [], []
        for r in rows:
            row = [1.0, math.log(law.impact_speed(r["drop_height"]))]
            if use_flow:
                row.append(math.log(r["flow_rate"]))
            A.append(row)
            y.append(r["angle"])
        coeffs, *_ = np.linalg.lstsq(np.array(A), np.array(y), rcond=None)
        law.impact_coeff = float(coeffs[1])
        law.flow_coeff = float(coeffs[2]) if use_flow else 0.0
        q_ref = law.flow_ref
        law.static_angle = float(
            coeffs[0]
            + coeffs[1] * math.log(law.impact_speed(law.ref_height))
            + (coeffs[2] * math.log(q_ref) if use_flow else 0.0)
        )
        return law


# ============================================================================
# PART 1.7  SANDFIELD -- FAST SAND SURFACE THAT OBEYS THE SANDLAW
# ============================================================================


class SandField:
    """
    Sand as a height field on a regular grid (fast model for design).

        surface = base + sand
        base : fixed terrain / existing geometry (sand cannot erode it)
        sand : sand thickness (>= 0)

    Rules:
      * mass conservation: poured mass / bulk density = sand volume
      * deposition over the landing disk of the stream (SandLaw.landing_radius)
      * avalanche relaxation: wherever the slope between two neighbour cells
        is steeper than tan(angle), sand slides down until it is not
        (angle from SandLaw.angle -> depends on drop height and flow rate)
      * the drop height is measured from the outlet to the CURRENT surface,
        so a growing pile gets a smaller fall height (physically correct)
    """

    _DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]

    def __init__(self, xmin, ymin, xmax, ymax, cell=0.005, base=None, law=None):
        self.law = law or SandLaw()
        self.cell = float(cell)
        self.x0, self.y0 = float(xmin), float(ymin)
        self.nx = max(int(math.ceil((xmax - xmin) / cell)) + 1, 3)
        self.ny = max(int(math.ceil((ymax - ymin) / cell)) + 1, 3)
        self.base = np.zeros((self.nx, self.ny)) if base is None else np.array(base, float)
        self.sand = np.zeros((self.nx, self.ny))
        gx = self.x0 + np.arange(self.nx) * cell
        gy = self.y0 + np.arange(self.ny) * cell
        self.gx, self.gy = np.meshgrid(gx, gy, indexing="ij")

    # --------------------------------------------------------------
    @property
    def surface(self):
        return self.base + self.sand

    def sand_volume(self):
        return float(self.sand.sum() * self.cell * self.cell)

    def height_at(self, x, y):
        i = int(round((x - self.x0) / self.cell))
        j = int(round((y - self.y0) / self.cell))
        i = min(max(i, 0), self.nx - 1)
        j = min(max(j, 0), self.ny - 1)
        return float(self.surface[i, j])

    def _slices(self, dx, dy):
        """Index slices so that a[xd, yd] and a[xs, ys] are neighbours (dx, dy)."""
        xs = slice(max(dx, 0), self.nx + min(dx, 0))
        ys = slice(max(dy, 0), self.ny + min(dy, 0))
        xd = slice(max(-dx, 0), self.nx + min(-dx, 0))
        yd = slice(max(-dy, 0), self.ny + min(-dy, 0))
        return xs, ys, xd, yd

    # --------------------------------------------------------------
    def deposit(self, x, y, volume, radius):
        """Spread a sand volume over a disk (the landing zone)."""
        radius = max(radius, 0.5 * self.cell)
        d2 = (self.gx - x) ** 2 + (self.gy - y) ** 2
        weight = np.clip(1.0 - d2 / (radius * radius), 0.0, None)  # parabolic
        total = weight.sum()
        if total <= 0.0:
            i = int(round((x - self.x0) / self.cell))
            j = int(round((y - self.y0) / self.cell))
            weight = np.zeros_like(self.sand)
            weight[min(max(i, 0), self.nx - 1), min(max(j, 0), self.ny - 1)] = 1.0
            total = 1.0
        self.sand += weight / total * volume / (self.cell * self.cell)

    def relax(self, angle_deg, max_iterations=5000, tolerance=None):
        """
        Avalanche until no neighbour slope exceeds tan(angle).
        Returns the number of iterations used.
        """
        tan_a = math.tan(math.radians(angle_deg))
        tol = 1e-3 * self.cell if tolerance is None else tolerance
        for it in range(max_iterations):
            surf = self.base + self.sand
            excesses = []
            total_excess = np.zeros_like(surf)
            max_excess = np.zeros_like(surf)
            for dx, dy in self._DIRS:
                dist = self.cell * math.hypot(dx, dy)
                neighbour = np.full_like(surf, np.inf)   # closed borders
                xs, ys, xd, yd = self._slices(dx, dy)
                neighbour[xd, yd] = surf[xs, ys]
                excess = np.maximum(surf - neighbour - tan_a * dist, 0.0)
                excesses.append(excess)
                total_excess += excess
                max_excess = np.maximum(max_excess, excess)
            if float(max_excess.max()) < tol:
                return it
            # move half of the largest excess, shared among the downhill
            # neighbours in proportion to their excess (stable, no overshoot)
            share = np.where(total_excess > 0.0, 0.5 * max_excess / np.maximum(total_excess, 1e-30), 0.0)
            # never move more sand than the cell has
            outflow = share * total_excess
            limit = np.where(outflow > self.sand, self.sand / np.maximum(outflow, 1e-30), 1.0)
            share *= limit
            for (dx, dy), excess in zip(self._DIRS, excesses):
                move = excess * share
                xs, ys, xd, yd = self._slices(dx, dy)
                self.sand -= move
                self.sand[xs, ys] += move[xd, yd]
        return max_iterations

    # --------------------------------------------------------------
    def pour(self, x, y, mass, outlet_height=None, drop_height=0.1,
             outlet_diameter=0.02, flow_rate=None, chunks=40):
        """
        Pour `mass` kg at (x, y).

        outlet_height : absolute height of the outlet. If None, the outlet
                        follows the pile and stays drop_height above it.
        drop_height   : used when outlet_height is None
        flow_rate     : kg/s, default from the outlet diameter (Beverloo)
        chunks        : the mass is poured in this many portions; angle and
                        landing radius are updated as the pile grows
        """
        law = self.law
        q = law.flow_rate(outlet_diameter) if flow_rate is None else flow_rate
        volume = mass / law.bulk_density
        for _ in range(int(chunks)):
            top = self.height_at(x, y)
            h = (outlet_height - top) if outlet_height is not None else drop_height
            h = max(h, 0.0)
            self.deposit(x, y, volume / chunks, law.landing_radius(h, outlet_diameter))
            self.relax(law.angle(h, q))
        return self

    def pour_along_path(self, points, mass_per_metre, drop_height=0.1,
                        outlet_height=None, outlet_diameter=0.02,
                        flow_rate=None, spacing=None, passes=1):
        """
        Move the outlet along a polyline (list of (x, y)) and pour
        mass_per_metre kg per metre of path (= flow_rate / outlet speed).
        """
        pts = np.asarray(points, float)[:, :2]
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        length = float(seg.sum())
        if length <= 0.0:
            return self.pour(pts[0, 0], pts[0, 1], mass_per_metre * self.cell,
                             outlet_height, drop_height, outlet_diameter, flow_rate)
        spacing = spacing or max(self.cell * 2.0, 0.5 * outlet_diameter)
        n = max(int(length / spacing), 1)
        s = np.linspace(0.0, length, n + 1)
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        xs = np.interp(s, cum, pts[:, 0])
        ys = np.interp(s, cum, pts[:, 1])
        mass_each = mass_per_metre * length / (n + 1) / passes
        for _ in range(int(passes)):
            for x, y in zip(xs, ys):
                self.pour(x, y, mass_each, outlet_height, drop_height,
                          outlet_diameter, flow_rate, chunks=2)
        return self

    def max_slope_angle(self):
        """Steepest slope on the sand (check: must not exceed the law angle)."""
        surf = self.surface
        gx = np.abs(np.diff(surf, axis=0)) / self.cell
        gy = np.abs(np.diff(surf, axis=1)) / self.cell
        has_sand = self.sand > 1e-9
        a = gx[(has_sand[1:, :] | has_sand[:-1, :])]
        b = gy[(has_sand[:, 1:] | has_sand[:, :-1])]
        steepest = max(float(a.max()) if a.size else 0.0, float(b.max()) if b.size else 0.0)
        return math.degrees(math.atan(steepest))


# ############################################################################
#
#   PART 2  BUILDING AND MODELING  (Rhino.Geometry)
#
#   Rule for all builders: LENGTHS ARE IN RHINO MODEL UNITS (points, curves,
#   drop height, outlet diameter, grain radius, cell size, outlet speed per
#   second). Masses in kg, flow rates in kg/s. Conversion to metres for
#   Part 1 happens inside.
#
#   Example GHPython 3 component:
#       from cdf.material_processes_sand import sand_pile_at_points
#       Mesh, Info = sand_pile_at_points(P, M, H, D)
#
# ############################################################################


def _require_rhino():
    if not HAS_RHINO:
        raise RuntimeError("This function needs Rhino (run it inside Rhino 8 / Grasshopper).")


def model_scale():
    """Model units per metre of the active Rhino document (1.0 if unknown)."""
    _require_rhino()
    try:
        return Rhino.RhinoMath.UnitScale(Rhino.UnitSystem.Meters, sc.doc.ModelUnitSystem)
    except Exception:
        return 1.0


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        return list(value)
    except TypeError:
        return [value]


def _longest(values, count, default):
    values = _as_list(values) or [default]
    return [float(values[min(i, len(values) - 1)]) for i in range(count)]


def _curve_xy(curve, spacing, s):
    """Points along a curve, every `spacing` model units, as (x, y) in metres."""
    length = curve.GetLength()
    n = max(int(length / max(spacing, 1e-9)), 1)
    params = curve.DivideByCount(n, True)
    return [(curve.PointAt(t).X / s, curve.PointAt(t).Y / s) for t in params]


# ---------------------------------------------------------------------------
# conversion: Part 1 objects -> Rhino geometry
# ---------------------------------------------------------------------------


def field_to_mesh(field, scale=None, sand_only=True):
    """SandField surface as a Rhino mesh (only where there is sand)."""
    _require_rhino()
    s = model_scale() if scale is None else scale
    surf = field.surface
    mesh = rg.Mesh()
    for i in range(field.nx):
        for j in range(field.ny):
            mesh.Vertices.Add(float(field.gx[i, j]) * s, float(field.gy[i, j]) * s,
                              float(surf[i, j]) * s)
    has = field.sand > 1e-9
    for i in range(field.nx - 1):
        for j in range(field.ny - 1):
            if sand_only and not (has[i, j] or has[i + 1, j] or has[i, j + 1] or has[i + 1, j + 1]):
                continue
            k = i * field.ny + j
            mesh.Faces.AddFace(k, k + field.ny, k + field.ny + 1, k + 1)
    mesh.Compact()
    mesh.Normals.ComputeNormals()
    return mesh


def base_from_mesh(field, mesh, scale=None):
    """Fill field.base with the height of a Rhino mesh below each grid cell."""
    _require_rhino()
    s = model_scale() if scale is None else scale
    bbox = mesh.GetBoundingBox(True)
    top = bbox.Max.Z + 1.0
    down = rg.Vector3d(0.0, 0.0, -1.0)
    for i in range(field.nx):
        for j in range(field.ny):
            origin = rg.Point3d(float(field.gx[i, j]) * s, float(field.gy[i, j]) * s, top)
            t = rg.Intersect.Intersection.MeshRay(mesh, rg.Ray3d(origin, down))
            if t >= 0.0:
                field.base[i, j] = max((top - t) / s, 0.0)
    return field


def grains_to_points(system, scale=None):
    _require_rhino()
    s = model_scale() if scale is None else scale
    return [rg.Point3d(float(p[0] * s), float(p[1] * s), float(p[2] * s))
            for p in system.x if np.isfinite(p).all()]


def _unit_sphere(slices=8, stacks=6):
    """
    Vertices and faces of a low-resolution unit sphere (poles + rings),
    built by hand so it does not depend on Rhino's sphere functions.
    Faces are ordered so all normals point outwards.
    """
    verts = [(0.0, 0.0, 1.0)]
    for i in range(1, stacks):
        phi = math.pi * i / stacks
        for j in range(slices):
            theta = 2.0 * math.pi * j / slices
            verts.append((math.sin(phi) * math.cos(theta),
                          math.sin(phi) * math.sin(theta),
                          math.cos(phi)))
    verts.append((0.0, 0.0, -1.0))
    bottom = len(verts) - 1

    def ring(i, j):
        return 1 + (i - 1) * slices + (j % slices)

    faces = []
    for j in range(slices):                               # top cap
        faces.append((0, ring(1, j), ring(1, j + 1)))
    for i in range(1, stacks - 1):                        # quads
        for j in range(slices):
            faces.append((ring(i, j), ring(i + 1, j), ring(i + 1, j + 1), ring(i, j + 1)))
    for j in range(slices):                               # bottom cap
        faces.append((ring(stacks - 1, j), bottom, ring(stacks - 1, j + 1)))
    return verts, faces


def grains_to_mesh(system, scale=None, u=8, v=6):
    """
    All grains as ONE mesh of small spheres (fast to display).
    u = segments around, v = segments from pole to pole.
    """
    _require_rhino()
    s = model_scale() if scale is None else scale
    unit_verts, unit_faces = _unit_sphere(max(int(u), 3), max(int(v), 2))
    n_unit = len(unit_verts)
    mesh = rg.Mesh()
    count = 0
    for p, r in zip(system.x, system.r):
        # plain Python floats for Rhino (numpy.float64 is not always converted)
        cx, cy, cz, radius = float(p[0] * s), float(p[1] * s), float(p[2] * s), float(r * s)
        if not (math.isfinite(cx) and math.isfinite(cy) and math.isfinite(cz)) or radius <= 0.0:
            continue
        offset = count * n_unit
        for vx, vy, vz in unit_verts:
            mesh.Vertices.Add(cx + radius * vx, cy + radius * vy, cz + radius * vz)
        for f in unit_faces:
            if len(f) == 3:
                mesh.Faces.AddFace(offset + f[0], offset + f[1], offset + f[2])
            else:
                mesh.Faces.AddFace(offset + f[0], offset + f[1], offset + f[2], offset + f[3])
        count += 1
    if count == 0:
        return None
    mesh.Normals.ComputeNormals()
    mesh.Compact()
    return mesh


def grains_to_field_mesh(system, cell=None, scale=None):
    """Top surface of a grain simulation as a mesh (any pile shape)."""
    _require_rhino()
    if system.count == 0:
        return None
    cell = 2.0 * system.material.radius if cell is None else cell
    x, r = system.x, system.r
    field = SandField(x[:, 0].min() - cell, x[:, 1].min() - cell,
                      x[:, 0].max() + cell, x[:, 1].max() + cell, cell)
    ix = np.clip(((x[:, 0] - field.x0) / cell).round().astype(int), 0, field.nx - 1)
    iy = np.clip(((x[:, 1] - field.y0) / cell).round().astype(int), 0, field.ny - 1)
    np.maximum.at(field.sand, (ix, iy), x[:, 2] + r)
    return field_to_mesh(field, scale)


def profile_curve(system, center=None, scale=None):
    """Radial surface profile of a grain pile as a polyline in the XZ plane."""
    _require_rhino()
    s = model_scale() if scale is None else scale
    radii, heights, center = pile_profile(system, center=center)
    if len(heights) == 0:
        return None
    mids = radii - 0.5 * radii[0]
    cx, cy = float(center[0]), float(center[1])
    pts = [rg.Point3d(cx * s, cy * s, float(heights[0]) * s)]
    pts += [rg.Point3d((cx + float(rr)) * s, cy * s, float(h) * s)
            for rr, h in zip(mids, heights)]
    return rg.PolylineCurve(pts)


# ---------------------------------------------------------------------------
# FAST builders (SandField + SandLaw)
# ---------------------------------------------------------------------------


def _field_around(xy_m, masses, law, cell_m, landing_m, extra=None):
    """A SandField large enough for all piles (cone at the flattest angle)."""
    xy = np.asarray(xy_m, float).reshape(-1, 2)
    vol = sum(masses) / law.bulk_density
    tan_min = math.tan(math.radians(law.min_angle))
    # cone V = pi r^2 h / 3 with h = r tan(angle)  ->  r = (3V / (pi tan))^(1/3)
    cone_radius = (3.0 * vol / (math.pi * tan_min)) ** (1.0 / 3.0)
    reach = cone_radius + landing_m + 4.0 * cell_m
    lo = xy.min(axis=0) - reach
    hi = xy.max(axis=0) + reach
    if extra is not None:
        lo = np.minimum(lo, extra[0])
        hi = np.maximum(hi, extra[1])
    return SandField(lo[0], lo[1], hi[0], hi[1], cell_m, law=law)


def _info(field, law, label):
    return (
        "{}: sand volume {:.4g} m3, steepest slope {:.1f} deg "
        "(law allows {:.1f}-{:.1f} deg)".format(
            label, field.sand_volume(), field.max_slope_angle(),
            law.min_angle, law.max_angle)
    )


def sand_pile_at_points(points, masses=0.5, drop_height=10.0, outlet_diameter=3.0,
                        flow_rate=None, follow_pile=False, cell=None, base_mesh=None,
                        law=None, chunks=40):
    """
    Pour sand at points with the fast SandField model.

    points          : list of Rhino.Geometry.Point3d (pour positions, XY used)
    masses          : kg per point (list or single value)
    drop_height     : outlet height above the ground [model units]
                      (follow_pile=True: above the pile top)
    outlet_diameter : outlet diameter [model units]; sets the flow rate
                      (Beverloo) and the stream width
    flow_rate       : kg/s, None = from the outlet diameter
    cell            : grid cell size [model units], default outlet/3
    base_mesh       : optional Rhino mesh the sand is poured onto
    law             : SandLaw (default: literature values + preliminary
                      calibration; use SandLaw.from_study for your own)

    Returns (mesh, info_text).
    Physics fulfilled: mass conservation, repose angle depending on the
    impact speed (drop height incl. air drag) and flow rate, landing spread
    from stream width + bounce (round tip for high drops).
    """
    _require_rhino()
    s = model_scale()
    law = law or SandLaw()
    pts = _as_list(points)
    m = _longest(masses, len(pts), 0.5)
    d_out = outlet_diameter / s
    h = drop_height / s
    cell_m = (cell / s) if cell else max(d_out / 3.0, 0.002)
    xy = [(p.X / s, p.Y / s) for p in pts]
    field = _field_around(xy, m, law, cell_m, law.landing_radius(h, d_out))
    if base_mesh is not None:
        base_from_mesh(field, base_mesh, s)
    for (x, y), mass in zip(xy, m):
        outlet_z = None if follow_pile else field.height_at(x, y) + h
        field.pour(x, y, mass, outlet_height=outlet_z, drop_height=h,
                   outlet_diameter=d_out, flow_rate=flow_rate, chunks=chunks)
    return field_to_mesh(field, s), _info(field, law, "sand_pile_at_points")


def sand_ridge_along_curve_physical(curve, drop_height=10.0, outlet_diameter=3.0,
                                    outlet_speed=5.0, flow_rate=None, passes=1,
                                    cell=None, base_mesh=None, law=None):
    """
    Move a pouring outlet along a curve (fast SandField model).

    curve        : Rhino curve (pour path, XY used)
    outlet_speed : speed of the outlet along the curve [model units / s]
    passes       : how many times the outlet travels the curve
    Mass per metre of path = flow_rate / outlet_speed, so a slow outlet or a
    wide outlet gives a higher, wider ridge -- like the real process.

    Returns (mesh, info_text).
    """
    _require_rhino()
    s = model_scale()
    law = law or SandLaw()
    d_out = outlet_diameter / s
    h = drop_height / s
    q = law.flow_rate(d_out) if flow_rate is None else flow_rate
    v = outlet_speed / s
    mass_per_m = q / max(v, 1e-9)
    cell_m = (cell / s) if cell else max(d_out / 3.0, 0.002)
    path = _curve_xy(curve, max(cell_m * 2.0, 0.5 * d_out) * s, s)
    length = curve.GetLength() / s
    total = mass_per_m * length * passes
    field = _field_around(path, [total / max(len(path), 1)], law, cell_m,
                          law.landing_radius(h, d_out),
                          extra=(np.min(path, axis=0), np.max(path, axis=0)))
    if base_mesh is not None:
        base_from_mesh(field, base_mesh, s)
    field.pour_along_path(path, mass_per_m, drop_height=h, outlet_diameter=d_out,
                          flow_rate=q, passes=passes)
    info = _info(field, law, "sand_ridge_along_curve_physical")
    info += ", {:.3g} kg/m, {:.3g} kg total".format(mass_per_m, total)
    return field_to_mesh(field, s), info


def sand_on_mesh(points, base_mesh, masses=0.5, drop_height=10.0, outlet_diameter=3.0,
                 flow_rate=None, cell=None, law=None):
    """Pour sand onto existing geometry (a Rhino mesh). Returns (mesh, info)."""
    return sand_pile_at_points(points, masses, drop_height, outlet_diameter,
                               flow_rate, False, cell, base_mesh, law)


# ---------------------------------------------------------------------------
# EXACT builders (full grain simulation, slow)
# ---------------------------------------------------------------------------


def _material_for(grain_radius, s, material):
    mat = material or SandMaterial()
    if grain_radius is not None:
        mat.radius = grain_radius / s
    return mat


def _grain_outputs(sim, s, center=None):
    system = sim.system
    res = analyse_pile(system, sim.emitters, center=center)
    return (grains_to_mesh(system, s), grains_to_points(system, s),
            grains_to_field_mesh(system, scale=s), format_result(res), res)


def grain_pour_at_points(points, total_mass=0.5, drop_height=10.0, outlet_diameter=3.0,
                         flow_rate=None, grain_radius=None, follow_pile=False,
                         max_time=8.0, material=None):
    """
    Full grain simulation (DEM): pour at each point until the sand rests.

    grain_radius : radius of a model particle [model units], default 4 mm
    Returns (sphere_mesh, points, surface_mesh, result_text, result_dict).
    Slow: minutes for ~1000 grains. Use it to check / calibrate the fast
    builders (parameter_study -> SandLaw.from_study).
    """
    _require_rhino()
    s = model_scale()
    mat = _material_for(grain_radius if grain_radius is not None else 0.004 * s, s, material)
    pts = _as_list(points)
    m = _longest(total_mass, len(pts), 0.5)
    emitters = [
        PourEmitter((p.X / s, p.Y / s), drop_height / s, outlet_diameter / s,
                    flow_rate, mass, follow_pile=follow_pile, material=mat)
        for p, mass in zip(pts, m)
    ]
    sim = Simulation(mat, emitters)
    sim.run_until_settled(max_time=max_time)
    center = (pts[0].X / s, pts[0].Y / s) if len(pts) == 1 else None
    return _grain_outputs(sim, s, center)


def grain_pour_along_curve(curve, drop_height=10.0, outlet_diameter=3.0, outlet_speed=5.0,
                           flow_rate=None, grain_radius=None, max_time=20.0, material=None):
    """
    Full grain simulation with the outlet moving along a curve.
    Returns (sphere_mesh, points, surface_mesh, result_text, result_dict).
    """
    _require_rhino()
    s = model_scale()
    mat = _material_for(grain_radius if grain_radius is not None else 0.004 * s, s, material)
    path = _curve_xy(curve, outlet_diameter, s)
    emitter = PourEmitter(path[0], drop_height / s, outlet_diameter / s, flow_rate,
                          total_mass=1e9, path=path, outlet_speed=outlet_speed / s,
                          material=mat)
    sim = Simulation(mat, [emitter])
    sim.run_until_settled(max_time=max_time)
    return _grain_outputs(sim, s)


def gh_pour(run, reset, drop_height=10.0, outlet_diameter=3.0, total_mass=0.3,
            grain_radius=None, steps_per_solve=200, follow_pile=True,
            key="cdf_sand_pour", show_spheres=True):
    """
    Grasshopper driver for the grain simulation: keeps it in
    scriptcontext.sticky and advances it each time a Timer recomputes.

    Inputs Run (toggle), Reset (button), drop height / outlet diameter /
    grain radius in model units, total mass in kg.
    Returns (points, sphere_mesh, profile_curve, status_text).
    """
    _require_rhino()
    s = model_scale()
    params = (drop_height, outlet_diameter, total_mass, grain_radius, follow_pile, s)
    state = sc.sticky.get(key)
    if reset or state is None or state["params"] != params:
        mat = _material_for(grain_radius if grain_radius is not None else 0.004 * s, s, None)
        emitter = PourEmitter((0.0, 0.0), drop_height / s, outlet_diameter / s, None,
                              total_mass, follow_pile=follow_pile, material=mat)
        state = {"sim": Simulation(mat, [emitter]), "params": params}
        sc.sticky[key] = state

    sim = state["sim"]
    if run and not sim.is_settled():
        sim.advance(steps_per_solve)
    system = sim.system
    if sim.is_settled():
        status = "Settled at t={:.2f}s: ".format(sim.time) + format_result(
            analyse_pile(system, sim.emitters, center=(0.0, 0.0)))
    else:
        status = "{} t={:.3f}s, grains={}, contacts={}, flow={:.3g} kg/s".format(
            "Running" if run else "Paused", sim.time, system.count,
            system.pair_count, sim.emitters[0].flow_rate)
    spheres = grains_to_mesh(system, s) if show_spheres and system.count else None
    return grains_to_points(system, s), spheres, profile_curve(system, (0.0, 0.0), s), status


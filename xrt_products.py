#!/usr/bin/env python3
"""
Swift-XRT light curve & spectrum maker  (easy, interactive)
===========================================================

Just run:
    python3 xrt_products.py

and answer the questions. Every question tells you the format and gives an
example. Press ENTER to accept the default shown in [brackets]. Type ? at any
question for more help.

It uses the official UKSSDC "XRT product builder" API
(https://www.swift.ac.uk/user_objects/), so the light curves and spectra are
made on the Leicester server and downloaded to your computer.

One-time setup:
    pip install swifttools astropy matplotlib
    Register your e-mail once at https://www.swift.ac.uk/user_objects/register.php
"""

import datetime as dt
import json
import os
import re
import sys
import time

os.environ.setdefault("MPLBACKEND", "Agg")   # draw plots straight to files, no window needed
import warnings
warnings.filterwarnings("ignore", message=".*non-interactive.*")

try:
    import swifttools.ukssdc.xrt_prods as ux
except ImportError:
    sys.exit("The 'swifttools' package is missing.  Install it with:  pip install swifttools")

try:
    from astropy.coordinates import SkyCoord
    from astropy.time import Time
    import astropy.units as u
    HAVE_ASTROPY = True
except ImportError:
    HAVE_ASTROPY = False

CONFIG_FILE = os.path.expanduser("~/.xrt_products.json")
SWIFT_EPOCH = "2001-01-01T00:00:00"

# ---------------------------------------------------------------- colours
_TTY = sys.stdout.isatty()


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def BOLD(t): return _c("1", t)
def CYAN(t): return _c("36", t)
def GREEN(t): return _c("32", t)
def YELLOW(t): return _c("33", t)
def RED(t): return _c("31", t)
def DIM(t): return _c("2", t)


class Invalid(ValueError):
    pass


# ======================================================================
# Prompt helpers
# ======================================================================
def section(title):
    print("\n" + CYAN("─" * 70))
    print(CYAN(BOLD(f"  {title}")))
    print(CYAN("─" * 70))


def _read(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        sys.exit("\nNo more input - stopping.")


def ask(question, fmt=None, example=None, default=None, convert=None, help=None):
    """Ask a free-text question; repeat until the answer is valid."""
    if question:
        print("\n" + BOLD(question))
    if fmt:
        print(DIM("   Format : ") + fmt)
    if example:
        print(DIM("   Example: ") + example)
    while True:
        text = _read(f"   > [{default}] " if default not in (None, "") else "   > ")
        if text == "?":
            print(YELLOW("   " + (help or "Follow the format and example shown above.")))
            continue
        if text == "" and default is not None:
            text = str(default)
        if text == "":
            print(RED("   ! Please type an answer (or ? for help)."))
            continue
        try:
            return convert(text) if convert else text
        except (ValueError, TypeError) as e:
            print(RED(f"   ! {e}" if isinstance(e, Invalid) else
                      f"   ! '{text}' is not in the right format - see 'Format' above (type ? for help)."))


def menu(question, options, default=1, help=None):
    """Numbered menu. options = list of (value, description). Returns the chosen value."""
    print("\n" + BOLD(question))
    for i, (_, desc) in enumerate(options, 1):
        print(f"   {i}) {desc}")

    def conv(text):
        if text.isdigit() and 1 <= int(text) <= len(options):
            return options[int(text) - 1][0]
        for val, _ in options:
            if text.lower() == str(val).lower():
                return val
        raise Invalid(f"Type a number from 1 to {len(options)}.")

    return ask(None, fmt=f"type a number 1-{len(options)}", default=default, convert=conv,
               help=help or "Type the number of your choice and press ENTER.")


def yes_no(question, default=True, help=None):
    def conv(t):
        t = t.lower()
        if t in ("y", "yes"):
            return True
        if t in ("n", "no"):
            return False
        raise Invalid("Please answer y or n.")
    return ask(question + DIM("  (y/n)"), default="y" if default else "n", convert=conv, help=help)


# ======================================================================
# Converters (what the user types -> what the API wants)
# ======================================================================
def to_email(s):
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s):
        raise Invalid("That doesn't look like an e-mail address (name@domain).")
    return s


def to_coords(s):
    """'RA Dec' in decimal degrees or sexagesimal (RA in hours) -> (ra, dec) in degrees."""
    parts = s.replace(",", " ").split()
    if len(parts) == 2:
        try:
            ra, dec = float(parts[0]), float(parts[1])
        except ValueError:
            ra = None
        if ra is not None:
            if not (0 <= ra < 360 and -90 <= dec <= 90):
                raise Invalid("RA must be 0-360 and Dec -90 to +90 degrees.")
            return ra, dec
    if not HAVE_ASTROPY:
        raise Invalid("Use decimal degrees (hh:mm:ss needs astropy installed).")
    half = len(parts) // 2
    try:
        c = SkyCoord(" ".join(parts[:half]), " ".join(parts[half:]), unit=(u.hourangle, u.deg))
    except Exception:
        raise Invalid("Could not read those coordinates - see the format above.")
    return round(float(c.ra.deg), 6), round(float(c.dec.deg), 6)


def to_datetime(s):
    """'YYYY-MM-DD', 'YYYY-MM-DD HH:MM[:SS]' or 'MJD 58000.5' -> datetime (UTC)."""
    s = s.strip()
    num = s.upper().replace("MJD", "").strip()
    try:
        mjd = float(num)
    except ValueError:
        mjd = None
    if mjd is not None:
        if not 51910 <= mjd <= 80000:
            raise Invalid("MJD must be after 51910 (2001-01-01, the Swift epoch).")
        return dt.datetime(1858, 11, 17) + dt.timedelta(days=mjd)
    for f in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d"):
        try:
            d = dt.datetime.strptime(s, f)
        except ValueError:
            continue
        if d.year < 2001:
            raise Invalid("Swift data start in 2004 - use a later date.")
        return d
    raise Invalid("Use YYYY-MM-DD (e.g. 2018-01-31), YYYY-MM-DD HH:MM, or MJD (e.g. MJD 58149).")


def server_time(d):
    """datetime -> UKSSDC time string (slashes in the date, because '-' means 'to')."""
    return d.strftime("%Y/%m/%dT%H:%M:%S")


def to_met(d):
    """datetime (UTC) -> Swift MET seconds."""
    if HAVE_ASTROPY:
        return float((Time(d, scale="utc") - Time(SWIFT_EPOCH, scale="utc")).sec)
    return (d - dt.datetime(2001, 1, 1)).total_seconds()


def to_obsids(s):
    ids = [x.strip() for x in s.replace(" ", ",").split(",") if x.strip()]
    bad = [x for x in ids if not re.fullmatch(r"\d{11}", x)]
    if bad:
        raise Invalid(f"ObsIDs have 11 digits (e.g. 00035019201). Not valid: {', '.join(bad)}")
    return ",".join(ids)


def to_redshift(s):
    if s.lower() in ("unknown", "none", "-", "no"):
        return None
    try:
        z = float(s)
    except ValueError:
        raise Invalid("Type a number like 0.536, or press ENTER if unknown.")
    if not 0 <= z < 15:
        raise Invalid("Redshift should be between 0 and 15.")
    return z


def number_between(lo, hi, cast=float):
    def conv(s):
        v = cast(s)
        if not lo <= v <= hi:
            raise Invalid(f"Must be between {lo} and {hi}.")
        return v
    return conv


def to_band(s):
    try:
        lo, hi = (float(x) for x in s.split("-"))
    except ValueError:
        raise Invalid("Write it as min-max, e.g. 0.3-10")
    if not 0.3 <= lo < hi <= 10:
        raise Invalid("Need 0.3 <= min < max <= 10 keV.")
    return lo, hi


def to_models(s):
    ms = [m.strip().lower() for m in s.split(",") if m.strip()]
    bad = [m for m in ms if m not in ("powerlaw", "apec", "blackbody")]
    if bad:
        raise Invalid(f"Unknown model: {', '.join(bad)}. Choose from powerlaw, apec, blackbody.")
    return ms


def to_alnum(s):
    if not s.isalnum():
        raise Invalid("Letters and digits only, no spaces.")
    return s


def to_gti(s):
    s = s.replace(" ", "")
    for it in s.split(","):
        try:
            a, b = (float(x) for x in it.split("-"))
        except ValueError:
            raise Invalid(f"'{it}' should be start-stop, e.g. 569248205-569334605")
        if a >= b:
            raise Invalid(f"In '{it}' the start must be smaller than the stop.")
    return s


def resolve_name(name):
    """Name -> (RA, Dec) via the CDS Sesame resolver (SIMBAD/NED/VizieR)."""
    if not HAVE_ASTROPY:
        return None
    try:
        c = SkyCoord.from_name(name)
        return round(float(c.ra.deg), 6), round(float(c.dec.deg), 6)
    except Exception:
        return None


# ======================================================================
# Questions
# ======================================================================
def load_config():
    try:
        with open(CONFIG_FILE) as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as fh:
            json.dump(cfg, fh)
    except Exception:
        pass


def get_email(cfg):
    saved = cfg.get("email")
    if saved and yes_no(f"Use your saved e-mail {saved}?", True):
        return saved
    email = ask("Your e-mail address (registered with the UKSSDC).",
                fmt="name@domain", example="you@university.edu", convert=to_email,
                help="Register once (free, no password) at https://www.swift.ac.uk/user_objects/register.php "
                     "and click the link in the confirmation e-mail.")
    cfg["email"] = email
    save_config(cfg)
    print(DIM(f"   (saved in {CONFIG_FILE} so you don't need to type it again)"))
    return email


def ask_sources():
    names = ask("Source name(s).",
                fmt="name as known to SIMBAD/NED; separate several sources with ;",
                example="3C 279      or      3C 279; PKS 0736+017",
                convert=lambda s: [n.strip() for n in s.split(";") if n.strip()],
                help="Any SIMBAD/NED name works: 'Mrk 421', 'GRB 060729', 'Swift J1753.5-0127'. "
                     "The coordinates are looked up for you and shown so you can check them.")
    sources = []
    for n in names:
        pos = resolve_name(n)
        if pos:
            print(GREEN(f"   ✓ {n}:  RA = {pos[0]:.5f}°   Dec = {pos[1]:+.5f}°"))
        else:
            print(YELLOW(f"   ! Could not look up '{n}' automatically - please type its position."))
            pos = ask(f"Coordinates of {n} (J2000).",
                      fmt="RA Dec in decimal degrees, or hh:mm:ss ±dd:mm:ss",
                      example="194.0465 -5.7893      or      12:56:11.2 -05:47:22",
                      convert=to_coords)
        sources.append({"name": n, "RA": pos[0], "Dec": pos[1], "z": None})
    return sources


def ask_data_selection():
    rng = menu("Which data should be used?",
               [("all", "All Swift-XRT data of the source  (recommended)"),
                ("dates", "Only data between two dates"),
                ("obsids", "Only specific observations (ObsIDs)")],
               help="Swift has observed many AGN hundreds of times. 'All' gives the full history; "
                    "a date range is quicker and good for studying one flare.")
    if rng == "all":
        return None, "all data"
    if rng == "obsids":
        ids = ask("ObsIDs to use.", fmt="11-digit ObsIDs separated by commas",
                  example="00035019201,00035019202", convert=to_obsids,
                  help="You can find ObsIDs at https://www.swift.ac.uk/swift_live/ or in HEASARC Browse.")
        return ids, f"ObsIDs {ids}"
    start = ask("Start date (UTC).", fmt="YYYY-MM-DD   or   YYYY-MM-DD HH:MM   or   MJD number",
                example="2018-01-01      or      MJD 58119", convert=to_datetime)
    while True:
        end = ask("End date (UTC). A plain date includes that whole day.",
                  fmt="YYYY-MM-DD   or   YYYY-MM-DD HH:MM   or   MJD number",
                  example="2018-12-31      or      MJD 58483", convert=to_datetime)
        if (end.hour, end.minute, end.second) == (0, 0, 0):
            end += dt.timedelta(days=1)
        if end > start:
            break
        print(RED("   ! The end must be after the start."))
    return f"{server_time(start)}-{server_time(end)}", f"{start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC"


def ask_lightcurve():
    lc = dict(minEnergy=0.3, maxEnergy=10.0, softLo=0.3, softHi=1.5, hardLo=1.5, hardHi=10.0,
              minSig=3.0, timeFormat="m", allowUL="both", allowBayes="both")
    lc["binMeth"] = menu("How should the light curve be binned?",
                         [("snapshot", "One point per snapshot (~1 orbit)  (recommended for AGN)"),
                          ("obsid", "One point per observation (ObsID)"),
                          ("time", "Fixed time bins - you choose the length"),
                          ("counts", "Fixed number of counts per bin  (good for GRBs / bright flares)")],
                         help="Snapshot binning is the usual choice for monitoring; counts binning "
                              "adapts the bin size to the brightness.")
    if lc["binMeth"] == "time":
        b = ask("Length of each time bin.", fmt="seconds",
                example="1000 (≈17 min)    5400 (≈1 orbit)    86400 (1 day)",
                default=1000, convert=number_between(2.51, 1e8))
        lc.update(pcBinTime=b, wtBinTime=b)
    elif lc["binMeth"] == "counts":
        c = ask("Counts per bin.", fmt="whole number (more counts = fewer but more precise points)",
                example="20", default=20, convert=number_between(5, 10000, int))
        lc.update(pcCounts=c, wtCounts=max(c, 30), dynamic=True)
    return lc


def ask_spectrum(sources):
    sp = dict(doNotFit=False, models=["powerlaw"], galactic=True)
    sp["timeslice"] = menu("How many spectra?",
                           [("single", "One spectrum from all the selected data  (recommended)"),
                            ("obsid", "One spectrum per observation (ObsID)"),
                            ("snapshot", "One spectrum per snapshot")])
    print("\n" + BOLD("Redshift of each source") + DIM("  (adds absorption intrinsic to the source)"))
    print(DIM("   Format : ") + "a number, or press ENTER if unknown")
    print(DIM("   Example: ") + "0.536")
    for s in sources:
        print(f"   {s['name']}:")
        s["z"] = ask(None, default="unknown", convert=to_redshift)
    return sp


def ask_advanced(glob, lc, sp):
    section("ADVANCED SETTINGS")
    print(DIM("   Press ENTER to keep each default."))
    if lc:
        lo, hi = ask("Energy band of the light curve.", fmt="min-max in keV, inside 0.3-10",
                     example="0.3-10", default="0.3-10", convert=to_band)
        cut = ask("Energy separating the soft and hard bands (for the hardness ratio).",
                  fmt="keV", example="1.5", default=1.5 if lo < 1.5 < hi else round((lo + hi) / 2, 2),
                  convert=number_between(lo + 0.01, hi - 0.01))
        lc.update(minEnergy=lo, maxEnergy=hi, softLo=lo, softHi=cut, hardLo=cut, hardHi=hi)
        lc["minSig"] = ask("Detection threshold - fainter points become upper limits.",
                           fmt="sigma", example="3", default=3.0, convert=number_between(0, 10))
        lc["timeFormat"] = menu("Time axis of the light curve.",
                                [("m", "MJD  (recommended)"),
                                 ("s", "Seconds (Swift MET, or seconds since T0 if you set one)")])
        if lc["timeFormat"] == "s" and yes_no("Measure times from a reference time T0 (e.g. a GRB trigger)?", False):
            t0 = ask("T0 (UTC).", fmt="YYYY-MM-DD HH:MM:SS   or   MJD number",
                     example="2019-01-15 12:30:00", convert=to_datetime)
            glob["T0"] = to_met(t0)
            print(DIM(f"   T0 = {glob['T0']:.1f} s Swift MET"))
    if sp:
        if yes_no("Fit the spectrum on the server (XSPEC)?", True):
            sp["models"] = ask("Model(s) to fit - each is fitted separately, with absorption.",
                               fmt="powerlaw, apec and/or blackbody, separated by commas",
                               example="powerlaw,blackbody", default="powerlaw", convert=to_models)
            sp["galactic"] = yes_no("Include fixed Galactic absorption (Willingale et al. 2013)?", True)
        else:
            sp["doNotFit"] = True
        if sp["timeslice"] == "single" and yes_no(
                "Instead of one spectrum, make up to 4 spectra in time intervals you define?", False):
            sp["timeslice"] = "user"
            n = ask("How many intervals?", fmt="1-4", default=2, convert=number_between(1, 4, int))
            for i in range(1, n + 1):
                sp[f"rname{i}"] = ask(f"Name of interval {i}.", fmt="letters and digits only",
                                      example=f"flare{i}", default=f"interval{i}", convert=to_alnum)
                sp[f"gti{i}"] = ask(f"Time range(s) of interval {i}.",
                                    fmt="start-stop in Swift MET seconds; several ranges separated by commas",
                                    example="569248205-569334605", convert=to_gti,
                                    help="Swift MET = seconds since 2001-01-01 00:00 UTC. "
                                         "If you set a T0, numbers below 1e8 mean seconds since T0.")
    glob["posErr"] = ask("How far (arcmin) the server may move the position when refining it.",
                         fmt="arcmin", example="1", default=glob["posErr"], convert=number_between(0.05, 20))


# ======================================================================
# Building, submitting, downloading
# ======================================================================
def build_request(email, src, glob, lc, sp, data_sel):
    req = ux.XRTProductRequest(email, silent=True, useDeprecate=False)
    req.setGlobalPars(name=src["name"], RA=float(src["RA"]), Dec=float(src["Dec"]), getTargs=True, **glob)
    sel = dict(whichData="user", useObs=data_sel) if data_sel else dict(whichData="all")
    if lc is not None:
        req.addLightCurve(**lc, **sel)
    if sp is not None:
        z = dict(hasRedshift=True, redshift=float(src["z"])) if src["z"] is not None else dict(hasRedshift=False)
        req.addSpectrum(**sp, **sel, **z)
    return req


def wait_for(jobs, poll=60):
    """Check all jobs once per minute (as the UKSSDC asks) until they finish."""
    pending = dict(jobs)
    while pending:
        for name, r in list(pending.items()):
            st = r.checkProductStatus()
            line = "   ".join(f"{p}: {s['statusText']}" for p, s in st.items())
            print(f"   {time.strftime('%H:%M:%S')}  {name:<18} {line}", flush=True)
            if r.complete:
                pending.pop(name)
        if pending:
            time.sleep(poll)


def _pretty(obj, indent=0):
    pad = "  " * indent
    if isinstance(obj, dict):
        return "\n".join(f"{pad}{k}:" + ("\n" + _pretty(v, indent + 1) if isinstance(v, (dict, list)) else f" {v}")
                         for k, v in obj.items())
    if isinstance(obj, list):
        return "\n".join(_pretty(v, indent) for v in obj)
    return f"{pad}{obj}"


def fit_table(fits):
    """Turn the nested spectral-fit dictionary into rows of the main numbers."""
    rows = []
    for rn in fits.get("rnames", []):
        reg = fits.get(rn, {})
        for mode in reg.get("Modes", []):
            md = reg.get(mode, {})
            for model in md.get("Models", []):
                f = md.get(model, {})
                row = {"spectrum": rn, "mode": mode, "model": model,
                       "exposure_s": md.get("Exposure"), "cstat": f.get("Cstat"), "dof": f.get("Dof")}
                for k in ("Gamma", "kT", "NH", "ObsFlux", "UnabsFlux"):
                    if k in f:
                        row[k] = f[k]
                        row[k + "Pos"] = f.get(k + "Pos")
                        row[k + "Neg"] = f.get(k + "Neg")
                rows.append(row)
    return rows


def print_fit_table(rows):
    def pm(r, k, fmt):
        if r.get(k) is None:
            return "-"
        return f"{fmt.format(r[k])} +{fmt.format(r[k + 'Pos'] or 0)} {fmt.format(r[k + 'Neg'] or 0)}"
    print(f"   {'spectrum':<18}{'model':<11}{'Gamma / kT':<28}{'NH (cm^-2)':<32}{'flux 0.3-10 keV (erg/cm2/s)':<36}C-stat/dof")
    for r in rows:
        shape = pm(r, "Gamma", "{:.2f}") if "Gamma" in r else pm(r, "kT", "{:.2f}")
        print(f"   {r['spectrum']:<18}{r['model']:<11}{shape:<28}{pm(r, 'NH', '{:.2e}'):<32}"
              f"{pm(r, 'ObsFlux', '{:.2e}'):<36}{r['cstat'] or 0:.1f}/{r['dof']}")


def download(name, req, outdir, xlog=False):
    outdir = os.path.abspath(outdir)          # swifttools changes directory while unpacking
    os.makedirs(outdir, exist_ok=True)
    st = req.checkProductStatus()
    for p, s in st.items():
        print((GREEN if s["statusCode"] == 4 else RED)(f"   {name} - {p}: {s['statusText']}"))

    try:
        req.downloadProducts(outdir, format="tar.gz", clobber=True)
        print(f"   product archives  -> {outdir}/")
    except Exception as e:
        print(RED(f"   could not download the archives: {e}"))

    if st.get("LightCurve", {}).get("statusCode") == 4:
        try:
            lc = req.retrieveLightCurve(returnData=True)
            for key in lc.get("Datasets", []):
                if hasattr(lc[key], "to_csv"):
                    lc[key].to_csv(os.path.join(outdir, f"lightcurve_{key}.csv"), index=False)
            fig, ax = req.plotLC(xlog=xlog, ylog=True)
            fig.suptitle(f"{name}  -  Swift-XRT")
            fig.savefig(os.path.join(outdir, "lightcurve.png"), dpi=150, bbox_inches="tight")
            print("   light curve       -> lightcurve_*.csv, lightcurve.png")
        except Exception as e:
            print(RED(f"   light-curve problem: {e}"))

    if st.get("Spectrum", {}).get("statusCode") == 4:
        try:
            fits = req.retrieveSpectralFits(returnData=True)
            with open(os.path.join(outdir, "spectral_fits_full.txt"), "w") as fh:
                fh.write(_pretty(fits) + "\n")
            rows = fit_table(fits)
            if rows:
                import csv
                keys = list(dict.fromkeys(k for r in rows for k in r))
                with open(os.path.join(outdir, "spectral_fits.csv"), "w", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=keys)
                    w.writeheader()
                    w.writerows(rows)
                print("   spectral fit results (errors are 90% confidence):")
                print_fit_table(rows)
            req.saveSpectralData(destDir=os.path.join(outdir, "spectrum"), saveImages=True,
                                 saveData=True, extract=True, clobber=True, skipErrors=True)
            print("   spectrum          -> spectral_fits.csv, spectral_fits_full.txt, spectrum/")
        except Exception as e:
            print(RED(f"   spectrum problem: {e}"))


def safe_dir(name):
    return re.sub(r"[^A-Za-z0-9_+.-]", "_", name)


# ======================================================================
# Workflows
# ======================================================================
def new_job(email):
    section("STEP 1 of 4 - SOURCES")
    sources = ask_sources()

    section("STEP 2 of 4 - WHAT TO MAKE")
    what = menu("What would you like?",
                [("both", "Light curve AND spectrum"),
                 ("lc", "Light curve only"),
                 ("spec", "Spectrum only")])
    data_sel, data_desc = ask_data_selection()

    section("STEP 3 of 4 - DETAILS")
    lc = ask_lightcurve() if what in ("both", "lc") else None
    sp = ask_spectrum(sources) if what in ("both", "spec") else None
    glob = dict(centroid=True, centMeth="iterative", posErr=1.0, useSXPS=False)
    if yes_no("Change advanced settings (energy band, fit models, T0, ...)?", False,
              help="Defaults: 0.3-10 keV, hardness split at 1.5 keV, 3-sigma detections, MJD time axis, "
                   "absorbed power-law fit including Galactic absorption."):
        ask_advanced(glob, lc, sp)
    outroot = ask("Folder to save the results in.", fmt="folder path", default="xrt_output")

    section("STEP 4 of 4 - CHECK AND SUBMIT")
    print(f"   E-mail       : {email}")
    for s in sources:
        z = (f", z = {s['z']}" if s["z"] is not None else ", z unknown") if sp else ""
        print(f"   Source       : {s['name']}  (RA {s['RA']:.4f}, Dec {s['Dec']:+.4f}{z})")
    print(f"   Data         : {data_desc}")
    if lc:
        print(f"   Light curve  : {lc['binMeth']} bins, {lc['minEnergy']}-{lc['maxEnergy']} keV, "
              f"hardness split at {lc['softHi']} keV, time axis in {'MJD' if lc['timeFormat'] == 'm' else 'seconds'}")
    if sp:
        fit = "no fit" if sp["doNotFit"] else "fit: " + ", ".join(sp["models"]) + (" + Galactic NH" if sp["galactic"] else "")
        print(f"   Spectrum     : {sp['timeslice']}, {fit}")
    print(f"   Results to   : {os.path.abspath(outroot)}/<source name>/")

    reqs = []
    for s in sources:
        r = build_request(email, s, glob, lc, sp, data_sel)
        ok, msg = r.isValid()
        if not ok:
            print(RED(f"\n   Problem with the settings for {s['name']}:\n{msg}"))
            return
        reqs.append((s["name"], r))

    if not yes_no("Submit now?", True):
        print("   Nothing was submitted.")
        return

    jobs = {}
    for name, r in reqs:
        if r.submit():
            print(GREEN(f"   ✓ {name}: job {r.JobID} submitted  ->  {r.URL}"))
            jobs[name] = r
        else:
            print(RED(f"   ✗ {name}: submission failed - {r.submitError}"))
    if not jobs:
        return

    section("WAITING FOR THE SERVER")
    print("   Checking once a minute. Sources with many observations can take an hour or more.")
    print("   You may press Ctrl-C at any time: the jobs keep running on the server, and you")
    print("   can download them later with option 2 of the main menu.")
    try:
        wait_for(jobs)
    except KeyboardInterrupt:
        print(YELLOW("\n   Stopped waiting. Your job IDs: " + ", ".join(str(r.JobID) for r in jobs.values())))
        return

    section("DOWNLOADING RESULTS")
    for name, r in jobs.items():
        download(name, r, os.path.join(outroot, safe_dir(name)), xlog="T0" in glob)
    print(GREEN(f"\n   Done! Everything is in {os.path.abspath(outroot)}/"))


def old_job(email):
    section("DOWNLOAD AN EARLIER JOB")
    try:
        jobs = ux.listOldJobs(email)
    except Exception as e:
        print(RED(f"   Could not get your job list: {e}"))
        jobs = []
    if jobs:
        print("   Your most recent jobs:")
        for j in sorted(jobs, key=lambda j: int(j["JobID"]), reverse=True)[:15]:
            prods = ", ".join(p for p in ("LightCurve", "Spectrum") if j.get(p))
            print(f"     {j['JobID']:>8}   {j['DateSubmitted']}   {j['Name']:<22} {prods}")
    job_id = ask("Job ID to download.", fmt="number (from the list above or the submission message)",
                 example="331136", convert=int)
    outroot = ask("Folder to save the results in.", fmt="folder path", default="xrt_output")
    r = ux.XRTProductRequest(email, silent=True, useDeprecate=False)
    try:
        r.copyOldJob(job_id, becomeThis=True)
    except Exception as e:
        print(RED(f"   Could not load job {job_id}: {e}"))
        return
    name = r.getGlobalPars().get("name") or str(job_id)
    if not r.complete:
        print(YELLOW("   This job is still running on the server."))
        if not yes_no("Wait for it to finish?", True):
            return
        try:
            wait_for({name: r})
        except KeyboardInterrupt:
            return
    download(name, r, os.path.join(outroot, safe_dir(name)))


def main():
    print(CYAN(BOLD("\n  Swift-XRT light curve & spectrum maker")))
    print(DIM("  UKSSDC XRT product builder - https://www.swift.ac.uk/user_objects/"))
    print(DIM("  Press ENTER to accept [defaults].  Type ? at any question for help.  Ctrl-C to quit."))
    if not HAVE_ASTROPY:
        print(YELLOW("  Tip: 'pip install astropy' enables automatic name look-up."))

    email = get_email(load_config())
    while True:
        choice = menu("What do you want to do?",
                      [("new", "Make a new light curve / spectrum"),
                       ("old", "Download the results of a job I submitted earlier"),
                       ("quit", "Quit")])
        if choice == "quit":
            break
        try:
            new_job(email) if choice == "new" else old_job(email)
        except KeyboardInterrupt:
            print(YELLOW("\n   Cancelled."))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBye.")

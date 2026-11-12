# SWIFT-XRT-ANALYSIS

**An easy, interactive Python tool for making *Swift*-XRT light curves and spectra.**

`xrt_products.py` uses the official
[UKSSDC XRT product builder](https://www.swift.ac.uk/user_objects/) Python API
(`swifttools`). It asks you a few simple questions (source name, what to make,
time range, binning, redshift). It then submits the job to the Leicester
server, waits for it to finish, and downloads ready-to-use results: light curves
(CSV and PNG), XSPEC-ready spectra and spectral-fit tables.

No HEASoft installation and no raw-data downloads are needed. The data
reduction (Evans et al. 2007, 2009) runs on the UKSSDC server.

![Example light curve of PKS 0736+017](examples/PKS0736+017_lightcurve.png)

---

## 1. Installation

```bash
pip install -r requirements.txt        # swifttools, astropy, matplotlib
```

Register your e-mail address with the UKSSDC once. It is free and needs no
password:
<https://www.swift.ac.uk/user_objects/register.php>, then click the link in the
confirmation e-mail.

## 2. Usage

```bash
python3 xrt_products.py
```

and answer the questions. Each question shows a **Format** and an **Example**.
Press **ENTER** to accept the default in `[brackets]`, and type **`?`** for help.

```
What do you want to do?
   1) Make a new light curve / spectrum
   2) Download the results of a job I submitted earlier
   3) Quit

Source name(s).
   Format : name as known to SIMBAD/NED; separate several sources with ;
   Example: 3C 279      or      3C 279; PKS 0736+017
   > 3C 279; PKS 0736+017
   ✓ 3C 279:  RA = 194.04653°   Dec = -5.78931°
   ✓ PKS 0736+017:  RA = 114.82514°   Dec = +1.61795°
```

| Step | You are asked for | Accepted format |
|------|-------------------|-----------------|
| 1 | Source name(s) | SIMBAD/NED name; several separated by `;`. Coordinates are looked up automatically. If the look-up fails you can type `RA Dec` in degrees or `hh:mm:ss ±dd:mm:ss` |
| 2 | Products | light curve, spectrum, or both |
| 2 | Data to use | all data / between two dates (`YYYY-MM-DD`, `YYYY-MM-DD HH:MM` or `MJD 58119`) / list of 11-digit ObsIDs |
| 3 | Light-curve binning | per snapshot, per ObsID, fixed time bins (seconds) or fixed counts per bin |
| 3 | Spectra | one spectrum, one per ObsID, or one per snapshot; redshift for each source (optional) |
| 3 | *Advanced (optional)* | energy band, soft/hard split energy, detection threshold, MJD or seconds time axis, T0, fit models (`powerlaw`, `apec`, `blackbody`), Galactic N<sub>H</sub>, up to 4 user-defined time intervals |
| 4 | Summary | check everything, then submit |

Your e-mail address is stored in `~/.xrt_products.json`, so you only type it once.
The script checks the server once a minute. You can press **Ctrl-C** at any time:
the job keeps running on the server, and you can download it later with menu
option **2**, which lists your previous jobs.

## 3. Output

For every source, the script writes a folder `xrt_output/<source name>/` containing:

| File | Content |
|------|---------|
| `lightcurve.png` | light-curve plot |
| `lightcurve_PC.csv`, `lightcurve_WT.csv` | count-rate light curves (time, errors, rate, errors, ObsID, …) |
| `lightcurve_*Soft/Hard/HR.csv` | soft-band and hard-band light curves and hardness ratio |
| `spectral_fits.csv` | fit results for each spectrum: photon index, N<sub>H</sub>, observed and unabsorbed 0.3–10 keV flux with 90 % errors, C-stat/dof |
| `spectral_fits_full.txt` | everything the server returned about the fits |
| `spectrum/` | source and background `.pi`, `.arf`, `.rmf` files, ready for XSPEC, plus plots of the fits |
| `lc.tar.gz`, `spec.tar.gz` | the original product archives |

Example fit table, printed to the screen and saved as
[`examples/PKS0736+017_spectral_fits.csv`](examples/PKS0736+017_spectral_fits.csv):

```
spectrum          model      Gamma / kT          flux 0.3-10 keV (erg/cm2/s)        C-stat/dof
Obs_00036373015   PowerLaw   1.98 +0.35 -0.29    3.53e-12 +7.74e-13 -6.26e-13       90.4/120
Obs_00036373016   PowerLaw   1.58 +0.28 -0.17    5.28e-12 +8.56e-13 -8.82e-13       116.9/156
```

## 4. Notes

- Sources with hundreds of observations (e.g. 3C 279) can take an hour or more
  on the server. A date range is much faster.
- Dates you type are converted to the server's format automatically. In ranges
  the server uses `/` in dates because `-` means "to"; the script handles this.
- The UKSSDC asks users not to submit very large numbers of jobs at once.

## 5. Acknowledgement

If you use these products in a publication, please acknowledge the UKSSDC and cite:

- Evans P. A. et al. 2007, A&A, 469, 379 — *An online repository of Swift/XRT light curves of GRBs*
- Evans P. A. et al. 2009, MNRAS, 397, 1177 — *Methods and results of an automatic analysis of a complete sample of Swift-XRT observations of GRBs*

and state that the work made use of data supplied by the UK Swift Science Data Centre at the University of Leicester.

## Author

**Zahir Shah** · <https://shahzahir.github.io/>

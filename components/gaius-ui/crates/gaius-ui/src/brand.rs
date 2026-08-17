//! Pluggable **logo** brand packs. Theme stays Keiretsu; product copy stays Gaius.

use flate2::read::GzDecoder;
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use tar::Archive;
use thiserror::Error;

pub const BRAND_WEATHERSHIP: &str = "weathership";
pub const BRAND_CLOUDERA: &str = "cloudera";
pub const BRAND_CUSTOM: &str = "custom";

pub const DEFAULT_CONFIG_PATH: &str = "build/dev/.gaius-ui.json";
const MAX_TGZ_BYTES: u64 = 4 * 1024 * 1024;

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct BrandManifest {
    pub id: String,
    #[serde(default)]
    pub display_name: String,
    #[serde(default = "default_logo_file")]
    pub logo_file: String,
    #[serde(default)]
    pub logo_alt: String,
    #[serde(default)]
    pub source: String,
}

fn default_logo_file() -> String {
    "logo.svg".into()
}

#[derive(Debug, Clone)]
pub struct Brand {
    pub id: String,
    pub display_name: String,
    pub logo_href: String,
    pub logo_alt: String,
    #[allow(dead_code)]
    pub pack_dir: PathBuf,
    pub has_logo: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct BrandOption {
    pub id: String,
    pub display_name: String,
    pub logo_href: String,
    pub logo_alt: String,
    pub has_logo: bool,
}

pub const ASK_CLT_PAIR: &str = "clt-pair";
pub const ASK_SAE_9B: &str = "sae-9b";

pub fn ask_complete_alias(backend: &str) -> &'static str {
    match backend {
        ASK_SAE_9B => "ask-sae",
        _ => "interpretable",
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DeploySettings {
    pub brand_id: String,
    #[serde(default = "default_ask_backend")]
    pub ask_backend: String,
}

fn default_ask_backend() -> String {
    ASK_CLT_PAIR.into()
}

impl Default for DeploySettings {
    fn default() -> Self {
        Self {
            brand_id: BRAND_WEATHERSHIP.into(),
            ask_backend: default_ask_backend(),
        }
    }
}

#[derive(Debug, Error)]
pub enum BrandError {
    #[error("brand pack not found: {0}\n  Guru: #UI.00000004.BRANDPACK")]
    NotFound(String),
    #[error("brand.json: {0}\n  Guru: #UI.00000004.BRANDPACK")]
    Manifest(String),
    #[error("logo file missing: {0}\n  Guru: #UI.00000004.BRANDPACK\n  Need logo.svg (or logo/lockup/lockup-mono-white.svg)")]
    MissingLogo(String),
    #[error("{0}\n  Guru: #UI.00000005.BRANDTGZ")]
    Tgz(String),
    #[error("io: {0}\n  Guru: #UI.00000006.BRANDSAVE")]
    Io(String),
}

impl DeploySettings {
    pub fn config_path() -> PathBuf {
        if let Ok(p) = std::env::var("GAIUS_UI_CONFIG") {
            return PathBuf::from(p);
        }
        if let Ok(root) = std::env::var("DEVENV_ROOT") {
            return PathBuf::from(root).join(DEFAULT_CONFIG_PATH);
        }
        PathBuf::from(DEFAULT_CONFIG_PATH)
    }

    pub fn load_or_bootstrap() -> Self {
        let path = Self::config_path();
        if path.is_file() {
            if let Ok(raw) = fs::read_to_string(&path) {
                if let Ok(s) = serde_json::from_str::<DeploySettings>(&raw) {
                    if !s.brand_id.is_empty() {
                        return s;
                    }
                }
            }
        }
        let mut s = Self::default();
        if let Ok(id) = std::env::var("GAIUS_UI_BRAND") {
            if !id.is_empty() {
                s.brand_id = id;
            }
        }
        s
    }

    pub fn save(&self, path: &Path) -> Result<(), BrandError> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| BrandError::Io(e.to_string()))?;
        }
        let raw = serde_json::to_string_pretty(self).map_err(|e| BrandError::Io(e.to_string()))?;
        let tmp = path.with_extension("json.tmp");
        fs::write(&tmp, raw.as_bytes()).map_err(|e| BrandError::Io(e.to_string()))?;
        fs::rename(&tmp, path).map_err(|e| BrandError::Io(e.to_string()))?;
        Ok(())
    }
}

#[allow(dead_code)]
pub fn assets_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../assets")
}

pub fn custom_dir() -> PathBuf {
    if let Ok(p) = std::env::var("GAIUS_UI_BRAND_CUSTOM") {
        return PathBuf::from(p);
    }
    if let Ok(root) = std::env::var("DEVENV_ROOT") {
        return PathBuf::from(root).join("build/dev/.gaius-ui-brand/custom");
    }
    PathBuf::from("build/dev/.gaius-ui-brand/custom")
}

pub fn pack_dir(assets_root: &Path, custom: &Path, id: &str) -> PathBuf {
    if id == BRAND_CUSTOM {
        if custom.join("logo.svg").is_file() {
            return custom.to_path_buf();
        }
    }
    assets_root.join("brand").join(id)
}

impl Brand {
    pub fn load_pack(pack_dir: &Path) -> Result<Self, BrandError> {
        if !pack_dir.is_dir() {
            return Err(BrandError::NotFound(pack_dir.display().to_string()));
        }
        let manifest = read_manifest(pack_dir)?;
        let logo_path = pack_dir.join(&manifest.logo_file);
        let has_logo = logo_path.is_file();
        if !has_logo && manifest.id != BRAND_CUSTOM {
            return Err(BrandError::MissingLogo(logo_path.display().to_string()));
        }
        let id = manifest.id;
        let logo_alt = if manifest.logo_alt.is_empty() {
            manifest.display_name.clone()
        } else {
            manifest.logo_alt
        };
        let display_name = if manifest.display_name.is_empty() {
            logo_alt.clone()
        } else {
            manifest.display_name
        };
        Ok(Self {
            logo_href: format!("/assets/brand/{id}/{}", manifest.logo_file),
            id,
            display_name,
            logo_alt,
            pack_dir: pack_dir.to_path_buf(),
            has_logo,
        })
    }
}

fn read_manifest(pack_dir: &Path) -> Result<BrandManifest, BrandError> {
    let manifest_path = pack_dir.join("brand.json");
    if manifest_path.is_file() {
        let raw = fs::read_to_string(&manifest_path).map_err(|e| BrandError::Manifest(e.to_string()))?;
        return serde_json::from_str(&raw).map_err(|e| BrandError::Manifest(e.to_string()));
    }
    Ok(BrandManifest {
        id: pack_dir
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("custom")
            .to_string(),
        display_name: "Custom".into(),
        logo_file: "logo.svg".into(),
        logo_alt: "Organization".into(),
        source: String::new(),
    })
}

pub fn load_brand_id(assets_root: &Path, custom: &Path, id: &str) -> Result<Brand, BrandError> {
    let dir = pack_dir(assets_root, custom, id);
    Brand::load_pack(&dir)
}

pub fn list_brand_packs(assets_root: &Path, custom: &Path) -> Vec<BrandOption> {
    let mut out = Vec::new();
    for id in [BRAND_WEATHERSHIP, BRAND_CLOUDERA, BRAND_CUSTOM] {
        let dir = pack_dir(assets_root, custom, id);
        match Brand::load_pack(&dir) {
            Ok(b) => out.push(BrandOption {
                id: b.id,
                display_name: b.display_name,
                logo_href: b.logo_href,
                logo_alt: b.logo_alt,
                has_logo: b.has_logo,
            }),
            Err(_) if id == BRAND_CUSTOM => out.push(BrandOption {
                id: BRAND_CUSTOM.into(),
                display_name: "Custom".into(),
                logo_href: String::new(),
                logo_alt: "Upload brand pack".into(),
                has_logo: false,
            }),
            Err(_) => {}
        }
    }
    out
}

fn allowed_archive_name(name: &str) -> bool {
    let lower = name.to_ascii_lowercase();
    if lower.contains("..") || lower.starts_with('/') {
        return false;
    }
    lower.ends_with(".svg")
        || lower.ends_with(".json")
        || lower.ends_with(".md")
        || lower.ends_with(".png")
        || lower.ends_with(".css")
}

/// Unpack a `.tgz` into `dest` (replaced atomically). Weathership kit or flat pack.
pub fn ingest_tgz(bytes: &[u8], dest: &Path) -> Result<Brand, BrandError> {
    if bytes.len() as u64 > MAX_TGZ_BYTES {
        return Err(BrandError::Tgz(format!(
            "pack larger than {MAX_TGZ_BYTES} bytes"
        )));
    }
    let parent = dest.parent().unwrap_or(Path::new("."));
    fs::create_dir_all(parent).map_err(|e| BrandError::Io(e.to_string()))?;
    let staging = parent.join(format!(
        ".custom-staging-{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_millis())
            .unwrap_or(0)
    ));
    let _ = fs::remove_dir_all(&staging);
    fs::create_dir_all(&staging).map_err(|e| BrandError::Io(e.to_string()))?;

    let dec = GzDecoder::new(bytes);
    let mut ar = Archive::new(dec);
    let entries = ar.entries().map_err(|e| BrandError::Tgz(e.to_string()))?;
    for ent in entries {
        let mut ent = ent.map_err(|e| BrandError::Tgz(e.to_string()))?;
        if !ent.header().entry_type().is_file() {
            continue;
        }
        let path = ent
            .path()
            .map_err(|e| BrandError::Tgz(e.to_string()))?
            .into_owned();
        let name = path.to_string_lossy();
        if !allowed_archive_name(&name) {
            continue;
        }
        let out = staging.join(&path);
        if let Some(p) = out.parent() {
            fs::create_dir_all(p).map_err(|e| BrandError::Io(e.to_string()))?;
        }
        let mut buf = Vec::new();
        ent.read_to_end(&mut buf)
            .map_err(|e| BrandError::Tgz(e.to_string()))?;
        fs::write(&out, buf).map_err(|e| BrandError::Io(e.to_string()))?;
    }

    let kit = locate_kit_root(&staging).ok_or_else(|| {
        BrandError::Tgz(
            "archive is not a brand pack.\n  Need logo.svg + favicon.svg, or a Weathership kit\n  (logo/lockup/lockup-mono-white.svg + favicon/favicon.svg)".into(),
        )
    })?;
    let packed = materialize_pack(&kit)?;

    if dest.exists() {
        fs::remove_dir_all(dest).map_err(|e| BrandError::Io(e.to_string()))?;
    }
    fs::rename(&packed, dest).map_err(|e| BrandError::Io(e.to_string()))?;
    let _ = fs::remove_dir_all(&staging);
    Brand::load_pack(dest)
}

fn locate_kit_root(staging: &Path) -> Option<PathBuf> {
    fn is_kit(p: &Path) -> bool {
        p.join("logo.svg").is_file()
            || p.join("logo/lockup/lockup-mono-white.svg").is_file()
            || p.join("brand.json").is_file()
    }
    if is_kit(staging) {
        return Some(staging.to_path_buf());
    }
    let rd = fs::read_dir(staging).ok()?;
    for ent in rd.flatten() {
        let p = ent.path();
        if p.is_dir() && is_kit(&p) {
            return Some(p);
        }
        let brand = p.join("brand");
        if brand.is_dir() && is_kit(&brand) {
            return Some(brand);
        }
    }
    None
}

fn materialize_pack(kit: &Path) -> Result<PathBuf, BrandError> {
    let out = kit.parent().unwrap_or(kit).join("normalized");
    let _ = fs::remove_dir_all(&out);
    fs::create_dir_all(&out).map_err(|e| BrandError::Io(e.to_string()))?;

    let logo_src = first_existing(kit, &[
        "logo.svg",
        "logo/lockup/lockup-mono-white.svg",
        "logo/lockup/lockup-horizontal.svg",
    ])
    .ok_or_else(|| BrandError::MissingLogo(kit.display().to_string()))?;
    let fav_src = first_existing(kit, &[
        "favicon.svg",
        "favicon/favicon.svg",
    ]);
    fs::copy(&logo_src, out.join("logo.svg")).map_err(|e| BrandError::Io(e.to_string()))?;
    if let Some(f) = fav_src {
        fs::copy(f, out.join("favicon.svg")).map_err(|e| BrandError::Io(e.to_string()))?;
    } else {
        fs::copy(&logo_src, out.join("favicon.svg")).map_err(|e| BrandError::Io(e.to_string()))?;
    }
    if let Some(m) = first_existing(kit, &["mark.svg", "logo/mark/mark-mono-white.svg", "logo/mark/mark.svg"])
    {
        let _ = fs::copy(m, out.join("mark.svg"));
    }
    let manifest = if kit.join("brand.json").is_file() {
        fs::read_to_string(kit.join("brand.json")).map_err(|e| BrandError::Manifest(e.to_string()))?
    } else {
        r#"{"id":"custom","display_name":"Custom","logo_file":"logo.svg","logo_alt":"Organization","source":"uploaded tgz"}"#.into()
    };
    fs::write(out.join("brand.json"), manifest).map_err(|e| BrandError::Io(e.to_string()))?;
    Ok(out)
}

fn first_existing(root: &Path, rels: &[&str]) -> Option<PathBuf> {
    for r in rels {
        let p = root.join(r);
        if p.is_file() {
            return Some(p);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::write::GzEncoder;
    use flate2::Compression;

    fn assets() -> PathBuf {
        assets_dir()
    }

    #[test]
    fn weathership_pack_ships() {
        let b = Brand::load_pack(&assets().join("brand/weathership")).unwrap();
        assert_eq!(b.id, "weathership");
        assert!(b.has_logo);
        assert_eq!(b.logo_href, "/assets/brand/weathership/logo.svg");
    }

    #[test]
    fn custom_placeholder_has_no_logo() {
        let b = Brand::load_pack(&assets().join("brand/custom")).unwrap();
        assert_eq!(b.id, "custom");
        assert!(!b.has_logo);
    }

    #[test]
    fn ingest_weathership_kit_layout() {
        let tmp = std::env::temp_dir().join(format!("gaius-brand-{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(tmp.join("in/logo/lockup")).unwrap();
        fs::create_dir_all(tmp.join("in/favicon")).unwrap();
        fs::write(
            tmp.join("in/logo/lockup/lockup-mono-white.svg"),
            b"<svg xmlns='http://www.w3.org/2000/svg'/>",
        )
        .unwrap();
        fs::write(
            tmp.join("in/favicon/favicon.svg"),
            b"<svg xmlns='http://www.w3.org/2000/svg'/>",
        )
        .unwrap();
        let tgz = tmp.join("pack.tgz");
        {
            let f = fs::File::create(&tgz).unwrap();
            let enc = GzEncoder::new(f, Compression::default());
            let mut builder = tar::Builder::new(enc);
            builder
                .append_path_with_name(
                    tmp.join("in/logo/lockup/lockup-mono-white.svg"),
                    "brand/logo/lockup/lockup-mono-white.svg",
                )
                .unwrap();
            builder
                .append_path_with_name(
                    tmp.join("in/favicon/favicon.svg"),
                    "brand/favicon/favicon.svg",
                )
                .unwrap();
            builder.finish().unwrap();
        }
        let bytes = fs::read(&tgz).unwrap();
        let dest = tmp.join("custom");
        let b = ingest_tgz(&bytes, &dest).unwrap();
        assert!(b.has_logo);
        assert!(dest.join("logo.svg").is_file());
        assert!(dest.join("favicon.svg").is_file());
        let _ = fs::remove_dir_all(&tmp);
    }
}

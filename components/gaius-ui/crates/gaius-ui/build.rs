use std::env;
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let manifest = PathBuf::from(env::var("CARGO_MANIFEST_DIR")?);
    let proto_root = manifest
        .join("../../../../external/signals-protocol/proto")
        .canonicalize()
        .unwrap_or_else(|_| manifest.join("../../../../external/signals-protocol/proto"));
    let engine = proto_root.join("zndx/engine/v1/engine.proto");
    println!("cargo:rerun-if-changed={}", engine.display());
    tonic_build::configure()
        .build_server(false)
        .build_client(true)
        .compile_protos(&[engine], &[proto_root])?;

    let gaius_proto_dir = manifest.join("../../proto");
    let gaius_surface = gaius_proto_dir.join("cognition_surface.proto");
    println!("cargo:rerun-if-changed={}", gaius_surface.display());
    tonic_build::configure()
        .build_server(false)
        .build_client(true)
        .compile_protos(&[&gaius_surface], &[&gaius_proto_dir])?;
    Ok(())
}

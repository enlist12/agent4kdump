use std::{
    env,
    fs,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
};
use tauri::Manager;

struct BackendProcess {
    child: Mutex<Option<Child>>,
}

#[tauri::command]
fn backend_status(state: tauri::State<BackendProcess>) -> String {
    let mut guard = state.child.lock().expect("backend process lock poisoned");
    match guard.as_mut() {
        Some(child) => match child.try_wait() {
            Ok(Some(status)) => {
                *guard = None;
                format!("stopped: {status}")
            }
            Ok(None) => "running".to_string(),
            Err(error) => format!("unknown: {error}"),
        },
        None => "not_started".to_string(),
    }
}

fn main() {
    tauri::Builder::default()
        .manage(BackendProcess {
            child: Mutex::new(None),
        })
        .setup(|app| {
            let child = start_backend(app.handle())?;
            let state = app.state::<BackendProcess>();
            *state.child.lock().expect("backend process lock poisoned") = child;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend_status])
        .on_window_event(|event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event.event() {
                let state = event.window().state::<BackendProcess>();
                let child = {
                    state
                        .child
                        .lock()
                        .expect("backend process lock poisoned")
                        .take()
                };
                if let Some(mut child) = child {
                    let _ = child.kill();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to run agent4kdump desktop client");
}

fn start_backend(app: tauri::AppHandle) -> tauri::Result<Option<Child>> {
    if port_is_open() {
        return Ok(None);
    }

    if let Some(path) = embedded_backend_path(&app) {
        return spawn_backend_exe(&path).map(Some).map_err(Into::into);
    }

    if let Some(path) = bundled_backend_path(&app) {
        return spawn_backend_exe(&path).map(Some).map_err(Into::into);
    }

    if let Some(root) = find_repo_root() {
        return spawn_dev_backend(&root).map(Some).map_err(Into::into);
    }

    Ok(None)
}

fn embedded_backend_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    const BACKEND_BYTES: &[u8] = include_bytes!("../../backend-dist/agent4kdump-backend");

    let filename = "agent4kdump-backend";
    let dir = app
        .path_resolver()
        .app_cache_dir()
        .unwrap_or_else(|| env::temp_dir().join("agent4kdump-client"));
    if fs::create_dir_all(&dir).is_err() {
        return None;
    }
    let path = dir.join(filename);
    let needs_write = fs::metadata(&path)
        .map(|metadata| metadata.len() != BACKEND_BYTES.len() as u64)
        .unwrap_or(true);
    if needs_write && fs::write(&path, BACKEND_BYTES).is_err() {
        return None;
    }
    make_executable(&path);
    Some(path)
}

#[cfg(all(unix, not(target_os = "macos")))]
fn make_executable(path: &Path) {
    use std::os::unix::fs::PermissionsExt;
    if let Ok(metadata) = fs::metadata(path) {
        let mut permissions = metadata.permissions();
        permissions.set_mode(0o755);
        let _ = fs::set_permissions(path, permissions);
    }
}

#[cfg(not(all(unix, not(target_os = "macos"))))]
fn make_executable(_path: &Path) {}

fn bundled_backend_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    let names = vec!["agent4kdump-backend"];

    for name in names {
        if let Some(path) = app.path_resolver().resolve_resource(name) {
            if path.exists() {
                return Some(path);
            }
        }
        if let Ok(exe) = env::current_exe() {
            if let Some(parent) = exe.parent() {
                let candidate = parent.join(name);
                if candidate.exists() {
                    return Some(candidate);
                }
            }
        }
    }
    None
}

fn spawn_backend_exe(path: &Path) -> std::io::Result<Child> {
    Command::new(path)
        .env("AGENT4KDUMP_CLIENT_API", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
}

fn spawn_dev_backend(root: &Path) -> std::io::Result<Child> {
    let mut command = Command::new("uv");
    command
        .args([
            "run",
            "uvicorn",
            "client.backend.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ])
        .current_dir(root)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    command.spawn()
}

fn find_repo_root() -> Option<PathBuf> {
    if let Ok(root) = env::var("AGENT4KDUMP_ROOT") {
        let path = PathBuf::from(root);
        if is_repo_root(&path) {
            return Some(path);
        }
    }

    let mut current = env::current_exe().ok()?.parent()?.to_path_buf();
    loop {
        if is_repo_root(&current) {
            return Some(current);
        }
        if !current.pop() {
            break;
        }
    }
    env::current_dir().ok().filter(|path| is_repo_root(path))
}

fn is_repo_root(path: &Path) -> bool {
    path.join("client").join("backend").join("app.py").exists()
        && path.join("pyproject.toml").exists()
}

fn port_is_open() -> bool {
    std::net::TcpStream::connect(("127.0.0.1", 8000)).is_ok()
}

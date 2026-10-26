// Windows 桌面端外壳：启动内嵌的 Python 服务（sidecar），再打开本地网页。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command};

use tauri::Manager;
use std::sync::Mutex;
use std::time::{Duration, Instant};

struct ServerProcess(Mutex<Option<Child>>);

fn sidecar_path() -> std::path::PathBuf {
    // 打包后：<安装目录>/binaries/videosorter-server.exe
    // 开发时：仓库根 server/ 直接 run
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|x| x.to_path_buf()))
        .unwrap_or_else(|| std::path::PathBuf::from("."));
    let name = if cfg!(windows) { "videosorter-server.exe" } else { "videosorter-server" };
    for cand in [
        exe_dir.join("binaries").join(name),
        exe_dir.join("binaries").join("videosorter-server").join(name),
        exe_dir.join(name.clone()),
        exe_dir.join("resources").join("binaries").join(name),
        exe_dir.join("resources").join("binaries").join("videosorter-server").join(name),
    ] {
        if cand.exists() {
            return cand;
        }
    }
    exe_dir.join(name)
}

fn spawn_server() -> Option<Child> {
    let exe = sidecar_path();
    if !exe.exists() {
        eprintln!("[videosorter] sidecar 未找到：{:?}", exe);
        return None;
    }
    let mut cmd = Command::new(&exe);
    cmd.args(["--host", "127.0.0.1", "--port", "8080"]);
    // 网页端可能和 sidecar 同级，也可能被 Tauri resources 打平到上一层，
    // 逐个候选找，找到就显式传 --web-dir（比让后端自己猜稳）。
    let mut webdist_cands: Vec<std::path::PathBuf> = Vec::new();
    if let Some(dir) = exe.parent() {
        webdist_cands.push(dir.join("webdist"));
        webdist_cands.push(dir.join("..").join("webdist"));
    }
    if let Ok(app_exe) = std::env::current_exe() {
        if let Some(exe_dir) = app_exe.parent() {
            webdist_cands.push(exe_dir.join("webdist"));
            webdist_cands.push(exe_dir.join("resources").join("webdist"));
            webdist_cands.push(exe_dir.join("resources").join("binaries").join("webdist"));
        }
    }
    for cand in webdist_cands {
        if cand.is_dir() {
            cmd.arg("--web-dir").arg(&cand);
            break;
        }
    }
    cmd.spawn()
        .map_err(|e| {
            eprintln!("[videosorter] 启动服务失败：{e}");
            e
        })
        .ok()
}

fn wait_healthy(timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if ureq::get("http://127.0.0.1:8080/api/health")
            .timeout(Duration::from_millis(800))
            .call()
            .is_ok()
        {
            return true;
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    false
}

fn main() {
    let child = spawn_server();
    wait_healthy(Duration::from_secs(25));

    tauri::Builder::default()
        .manage(ServerProcess(Mutex::new(child)))
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                if let Some(state) = app.try_state::<ServerProcess>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(child) = guard.as_mut() {
                            let _ = child.kill();
                            let _ = child.wait();
                        }
                    }
                }
            }
        });
}

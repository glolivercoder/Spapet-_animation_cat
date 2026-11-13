"""
backend/moco/gitea_manager.py
Gerenciamento de Instância Nativa do Gitea (Padrão MOCO - Zero Docker).
Orquestra o binário local do Gitea, repositórios isolados por projeto,
exclusões em .git/info/exclude (sem .gitignore), auto-commits, pushs e backups.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import atexit
from pathlib import Path
from typing import Optional, Dict, Any, List

ROOT = Path(__file__).resolve().parent.parent.parent
GITEA_DIR = ROOT / "local_services" / "gitea"
GITEA_CONF_DIR = GITEA_DIR / "custom" / "conf"
GITEA_DATA_DIR = GITEA_DIR / "data"


class GiteaManager:
    def __init__(self, port: int = 3008):
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.project_watchers: Dict[str, subprocess.Popen] = {}
        self.project_dirs: Dict[str, Path] = {}
        self._ensure_dirs()
        atexit.register(self.stop_all_watchers)
        atexit.register(self.stop)

    def _ensure_dirs(self) -> None:
        GITEA_CONF_DIR.mkdir(parents=True, exist_ok=True)
        GITEA_DATA_DIR.mkdir(parents=True, exist_ok=True)

    def generate_config(self, app_name: str = "Devmaster Git Hub") -> Path:
        """Gera o arquivo app.ini apontando para banco de dados SQLite local embutido."""
        ini_path = GITEA_CONF_DIR / "app.ini"
        content = (
            f"APP_NAME = {app_name}\n"
            "RUN_MODE = prod\n"
            "RUN_USER = devmaster\n\n"
            "[database]\n"
            "DB_TYPE = sqlite3\n"
            f"PATH    = {GITEA_DATA_DIR / 'gitea.db'}\n\n"
            "[repository]\n"
            f"ROOT    = {GITEA_DATA_DIR / 'repositories'}\n\n"
            "[server]\n"
            "PROTOCOL     = http\n"
            "DOMAIN       = localhost\n"
            f"HTTP_PORT    = {self.port}\n"
            "DISABLE_SSH  = true\n"
            "OFFLINE_MODE = true\n\n"
            "[security]\n"
            "INSTALL_LOCK = true\n"
            "SECRET_KEY   = devmaster_moco_gitea_key_2026\n\n"
            "[service]\n"
            "DISABLE_REGISTRATION = false\n"
            "REQUIRE_SIGNIN_VIEW  = false\n"
        )
        ini_path.write_text(content, encoding="utf-8")
        return ini_path

    def get_binary_path(self) -> Optional[Path]:
        """Verifica se o executável do Gitea existe na pasta local_services/gitea."""
        exe_name = "gitea.exe" if os.name == "nt" else "gitea"
        local_bin = GITEA_DIR / exe_name
        if local_bin.exists():
            return local_bin
        return None

    def get_status(self) -> Dict[str, Any]:
        bin_path = self.get_binary_path()
        return {
            "binary_installed": bin_path is not None,
            "binary_path": str(bin_path) if bin_path else None,
            "config_exists": (GITEA_CONF_DIR / "app.ini").exists(),
            "port": self.port,
            "data_dir": str(GITEA_DATA_DIR),
            "is_running": self.process is not None and self.process.poll() is None,
            "active_watchers": len([p for p in self.project_watchers.values() if p.poll() is None]),
        }

    def start_if_available(self) -> bool:
        """Inicia o Gitea nativamente se o binário existir."""
        bin_path = self.get_binary_path()
        if not bin_path or (self.process and self.process.poll() is None):
            return False

        self.generate_config()
        env = os.environ.copy()
        env["GITEA_WORK_DIR"] = str(GITEA_DIR)

        try:
            self.process = subprocess.Popen(
                [str(bin_path), "web", "--config", str(GITEA_CONF_DIR / "app.ini")],
                cwd=str(GITEA_DIR),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            return False

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process = None

    def _resolve_project_dir(self, project_id: str) -> Path:
        """Determina o diretório local do projeto a partir do ID ou catálogo."""
        if project_id in self.project_dirs and self.project_dirs[project_id].exists():
            return self.project_dirs[project_id]

        try:
            from core import project_catalog
            projects = project_catalog.list_projects()
            proj = None
            if project_id in ("current", "active"):
                for p in projects:
                    if p.get("status") == "active":
                        proj = p
                        break
                if not proj and projects:
                    proj = projects[0]
            else:
                for p in projects:
                    if p.get("id") == project_id:
                        proj = p
                        break

            if proj and proj.get("folder_path"):
                p_path = Path(proj["folder_path"])
                p_path.mkdir(parents=True, exist_ok=True)
                self.project_dirs[project_id] = p_path.resolve()
                return p_path.resolve()

            if proj:
                slug = re.sub(r"[^a-zA-Z0-9]+", "-", proj.get("name", project_id).lower()).strip("-") or "projeto"
                p_path = ROOT / "workspace" / "projects" / slug
                p_path.mkdir(parents=True, exist_ok=True)
                self.project_dirs[project_id] = p_path.resolve()
                return p_path.resolve()
        except Exception:
            pass

        slug = re.sub(r"[^a-zA-Z0-9]+", "-", project_id.lower()).strip("-") or "projeto"
        p_path = ROOT / "workspace" / "projects" / slug
        p_path.mkdir(parents=True, exist_ok=True)
        self.project_dirs[project_id] = p_path.resolve()
        return p_path.resolve()

    def is_watcher_running(self, project_id: str) -> bool:
        proc = self.project_watchers.get(project_id)
        return proc is not None and proc.poll() is None

    def start_project_watcher(self, project_id: str, proj_dir: Path, repo_url: str) -> bool:
        """Inicia o watcher em PowerShell para monitorar o diretório do projeto em background."""
        if self.is_watcher_running(project_id):
            return True

        watcher_script = ROOT / "scripts" / "gitea_watcher.ps1"
        if not watcher_script.exists():
            return False

        ps_exe = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
        try:
            cmd = [
                ps_exe,
                "-ExecutionPolicy", "Bypass",
                "-NoProfile",
                "-File", str(watcher_script),
                "-ProjectPath", str(proj_dir),
                "-GiteaUrl", repo_url,
                "-DebounceSeconds", "30",
                "-BackupIntervalHours", "6",
                "-MaxBackupsToKeep", "14"
            ]
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.project_watchers[project_id] = proc
            return True
        except Exception:
            return False

    def stop_all_watchers(self) -> None:
        for pid, proc in list(self.project_watchers.items()):
            try:
                if proc and proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
        self.project_watchers.clear()

    def init_project_repo(self, project_id: str, project_name: str, folder_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Incorpora o repositório local e agente Gitea ao novo projeto.
        Configura .git/info/exclude (sem .gitignore), inicializa git, cria commit inicial e remote local.
        """
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", project_name.lower()).strip("-") or "projeto"
        if folder_path:
            proj_dir = Path(folder_path).resolve()
        else:
            proj_dir = (ROOT / "workspace" / "projects" / slug).resolve()

        proj_dir.mkdir(parents=True, exist_ok=True)
        self.project_dirs[project_id] = proj_dir
        git_dir = proj_dir / ".git"

        # 1. git init se necessário
        if not git_dir.is_dir():
            subprocess.run(["git", "init"], cwd=str(proj_dir), capture_output=True, check=False)

        # 2. Configurar exclusões locais em .git/info/exclude (Sem .gitignore convencional)
        exclude_file = git_dir / "info" / "exclude"
        exclude_file.parent.mkdir(parents=True, exist_ok=True)
        exclude_rules = [
            "# GiteaDog Local Exclusions (Sem .gitignore convencional)",
            ".venv/",
            "venv/",
            "env/",
            "__pycache__/",
            "*.pyc",
            "node_modules/",
            "dist/",
            "build/",
            "*.log",
            "*.db",
            "*.sqlite",
            "*.sqlite3",
            "storage/",
            "vector_store/",
            ".chroma/",
            "backups/",
        ]
        existing_text = exclude_file.read_text(encoding="utf-8") if exclude_file.exists() else ""
        new_lines = [r for r in exclude_rules if r not in existing_text]
        if new_lines:
            with open(exclude_file, "a", encoding="utf-8") as f:
                if existing_text and not existing_text.endswith("\n"):
                    f.write("\n")
                f.write("\n".join(new_lines) + "\n")

        # 3. Criar README.md inicial se o diretório não tiver arquivos do usuário
        readme_file = proj_dir / "README.md"
        if not readme_file.exists():
            readme_content = (
                f"# {project_name}\n\n"
                f"Projeto auto-gerenciado e versionado pelo **Agente Caramelo Git DevOps (GiteaDog)**.\n\n"
                f"- **Remote Gitea Local**: `http://127.0.0.1:{self.port}/agent/{slug}.git`\n"
                f"- **Exclusões Locais**: gerenciadas via `.git/info/exclude` (Zero poluição de `.gitignore`)\n"
                f"- **Monitoramento**: Watcher nativo com debounce de 30s e backups a cada 6h (14 retidos).\n"
            )
            readme_file.write_text(readme_content, encoding="utf-8")

        # 4. Criar commit inicial se não houver commits
        check_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(proj_dir), capture_output=True, check=False)
        if check_head.returncode != 0:
            subprocess.run(["git", "add", "-A"], cwd=str(proj_dir), capture_output=True, check=False)
            subprocess.run(
                [
                    "git",
                    "-c", "user.name=GiteaDog DevOps",
                    "-c", "user.email=giteadog@local",
                    "commit",
                    "-m", f"chore(init): initial commit for project {project_name} [GiteaDog DevOps]",
                ],
                cwd=str(proj_dir),
                capture_output=True,
                check=False
            )

        # 5. Configurar Remote local no Gitea
        repo_url = f"http://127.0.0.1:{self.port}/agent/{slug}.git"
        check_remote = subprocess.run(["git", "remote"], cwd=str(proj_dir), capture_output=True, text=True, check=False)
        remotes = [r.strip() for r in check_remote.stdout.split() if r.strip()]
        if "origin" not in remotes:
            subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=str(proj_dir), capture_output=True, check=False)
        else:
            subprocess.run(["git", "remote", "set-url", "origin", repo_url], cwd=str(proj_dir), capture_output=True, check=False)

        # 6. Criar diretório de backups do projeto
        (proj_dir / "backups").mkdir(parents=True, exist_ok=True)

        # 7. Iniciar / Registrar monitoramento contínuo
        self.start_project_watcher(project_id, proj_dir, repo_url)

        return {
            "status": "monitoring",
            "project_id": project_id,
            "project_name": project_name,
            "slug": slug,
            "folder_path": str(proj_dir),
            "repo_url": repo_url,
            "agent": "giteadog",
            "is_git_initialized": True,
            "exclude_configured": True,
            "watcher_active": self.is_watcher_running(project_id),
        }

    def list_project_commits(self, project_id: str, limit: int = 15) -> List[Dict[str, str]]:
        """Retorna histórico de commits do repositório do projeto."""
        proj_dir = self._resolve_project_dir(project_id)
        if not proj_dir.exists() or not (proj_dir / ".git").exists():
            return []
        try:
            res = subprocess.run(
                ["git", "log", f"-n{limit}", "--pretty=format:%h|%an|%ad|%s", "--date=short"],
                cwd=str(proj_dir),
                capture_output=True,
                text=True,
                check=False
            )
            commits = []
            if res.returncode == 0 and res.stdout.strip():
                for line in res.stdout.strip().split("\n"):
                    parts = line.split("|", 3)
                    if len(parts) == 4:
                        commits.append({
                            "hash": parts[0],
                            "author": parts[1],
                            "date": parts[2],
                            "message": parts[3],
                        })
            return commits
        except Exception:
            return []

    def create_project_backup(self, project_id: str) -> Dict[str, Any]:
        """Gera snapshot imediato (.bundle) na pasta backups do projeto."""
        import datetime
        proj_dir = self._resolve_project_dir(project_id)
        backup_dir = proj_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        bundle_file = backup_dir / f"git_bundle_{now_str}.bundle"

        try:
            subprocess.run(
                ["git", "bundle", "create", str(bundle_file), "--all"],
                cwd=str(proj_dir),
                capture_output=True,
                check=False
            )
            all_bundles = sorted(backup_dir.glob("git_bundle_*.bundle"), key=lambda f: f.stat().st_mtime, reverse=True)
            if len(all_bundles) > 14:
                for old in all_bundles[14:]:
                    try:
                        old.unlink()
                    except Exception:
                        pass

            return {
                "status": "ok",
                "project_id": project_id,
                "bundle_file": str(bundle_file),
                "created_at": now_str,
                "size_bytes": bundle_file.stat().st_size if bundle_file.exists() else 0,
                "total_backups": min(len(all_bundles), 14),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def sync_project(self, project_id: str, message: Optional[str] = None) -> Dict[str, Any]:
        """Executa git add -A, commit com timestamp e tentativa de push para origin HEAD."""
        import datetime
        proj_dir = self._resolve_project_dir(project_id)
        try:
            subprocess.run(["git", "add", "-A"], cwd=str(proj_dir), capture_output=True, check=False)
            status_res = subprocess.run(["git", "status", "--porcelain"], cwd=str(proj_dir), capture_output=True, text=True, check=False)
            committed = False
            msg = message or f"auto: manual sync {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [GiteaDog]"
            if status_res.stdout.strip():
                commit_res = subprocess.run(
                    [
                        "git",
                        "-c", "user.name=GiteaDog DevOps",
                        "-c", "user.email=giteadog@local",
                        "commit",
                        "-m", msg,
                    ],
                    cwd=str(proj_dir),
                    capture_output=True,
                    text=True,
                    check=False
                )
                committed = (commit_res.returncode == 0)

            push_res = subprocess.run(["git", "push", "origin", "HEAD"], cwd=str(proj_dir), capture_output=True, text=True, check=False)
            pushed = (push_res.returncode == 0)

            commits = self.list_project_commits(project_id, limit=5)
            return {
                "status": "ok",
                "project_id": project_id,
                "committed": committed,
                "pushed": pushed,
                "latest_commit": commits[0] if commits else None,
                "commit_count": len(commits)
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_project_gitea_status(self, project_id: str) -> Dict[str, Any]:
        """Retorna status completo de versionamento e monitoramento do projeto."""
        proj_dir = self._resolve_project_dir(project_id)
        is_git = (proj_dir / ".git").is_dir()
        exclude_ok = (proj_dir / ".git" / "info" / "exclude").exists()
        commits = self.list_project_commits(project_id, limit=5)
        backups = list((proj_dir / "backups").glob("*.bundle")) if (proj_dir / "backups").exists() else []

        slug = re.sub(r"[^a-zA-Z0-9]+", "-", project_id.lower()).strip("-")
        return {
            "status": "monitoring" if is_git else "uninitialized",
            "project_id": project_id,
            "folder_path": str(proj_dir),
            "repo_url": f"http://127.0.0.1:{self.port}/agent/{slug}.git",
            "is_git_initialized": is_git,
            "exclude_configured": exclude_ok,
            "watcher_active": self.is_watcher_running(project_id),
            "agent": "giteadog",
            "commits_count": len(commits),
            "latest_commit": commits[0] if commits else None,
            "backups_count": len(backups),
        }

    # Compatibilidade com chamadas raiz existentes
    def list_local_commits(self, limit: int = 10) -> List[Dict[str, str]]:
        """Retorna os commits mais recentes do repositório root usando git log."""
        try:
            res = subprocess.run(
                ["git", "log", f"-n{limit}", "--pretty=format:%h|%an|%ad|%s", "--date=short"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            commits = []
            if res.returncode == 0 and res.stdout.strip():
                for line in res.stdout.strip().split("\n"):
                    parts = line.split("|", 3)
                    if len(parts) == 4:
                        commits.append({
                            "hash": parts[0],
                            "author": parts[1],
                            "date": parts[2],
                            "message": parts[3],
                        })
            return commits
        except Exception:
            return []

    def create_backup_snapshot(self) -> Dict[str, Any]:
        """Gera snapshot de backup no diretório local_services/gitea/backups."""
        backup_dir = GITEA_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        import datetime
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        bundle_file = backup_dir / f"git_bundle_{now_str}.bundle"

        try:
            subprocess.run(
                ["git", "bundle", "create", str(bundle_file), "--all"],
                cwd=str(ROOT),
                capture_output=True,
                check=False,
            )
            return {
                "status": "ok",
                "bundle_file": str(bundle_file),
                "created_at": now_str,
                "size_bytes": bundle_file.stat().st_size if bundle_file.exists() else 0,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}


gitea_manager = GiteaManager()

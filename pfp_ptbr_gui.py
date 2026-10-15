#!/usr/bin/env python3
"""
Tradutor do Patch for Purists para PT-BR.
Baixa o tes3conv sozinho (GitHub: Greatness7/tes3conv).
"""
import gc
import json
import os
import queue
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import urllib.request
import webbrowser
import zipfile
import tkinter as tk
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "Patch for Purists — Tradução PT-BR"
NEXUS_URL = "https://www.nexusmods.com/morrowind/mods/60355"
TES3CONV_API = "https://api.github.com/repos/Greatness7/tes3conv/releases/latest"
IS_WIN = sys.platform.startswith("win")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

MASTERS = ["Morrowind.esm", "Tribunal.esm", "Bloodmoon.esm"]
SPEAKER_FIELDS = ("speaker_cell", "speaker_race", "speaker_class",
                  "speaker_faction", "player_faction")
ADDTOPIC_RE = re.compile(r'(?i)(\bAddTopic\s+)"([^"]+)"')

# função de log (a interface substitui por uma que escreve na caixa de texto)
LOG = print


class PFPError(Exception):
    """Erro 'esperado' que deve ser mostrado ao usuário."""


# ------------------------------------------------------------ pastas / tes3conv
def app_dir():
    """Pasta do .exe (ou do script, se rodando como .py)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def tools_dir():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local/share")
    d = Path(base) / "PFP_PTBR" / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_tes3conv():
    exe_name = "tes3conv.exe" if IS_WIN else "tes3conv"
    for folder in (tools_dir(), app_dir()):
        p = folder / exe_name
        if p.is_file():
            return str(p)
    return shutil.which("tes3conv")


def pick_asset(assets):
    """Escolhe o arquivo do release certo para o sistema atual."""
    keys = ("win", "windows") if IS_WIN else (
        ("mac", "darwin", "apple") if sys.platform == "darwin" else ("linux",))
    scored = []
    for a in assets:
        n = a["name"].lower()
        if n.endswith((".sha256", ".txt", ".md5", ".sig")):
            continue
        score = 0
        if any(k in n for k in keys):
            score += 10
        if IS_WIN and n.endswith(".exe"):
            score += 5
        if n.endswith(".zip"):
            score += 1
        scored.append((score, a))
    scored.sort(key=lambda t: -t[0])
    if scored and scored[0][0] > 0:
        return scored[0][1]
    # se só existe um arquivo, usa ele
    return scored[0][1] if len(scored) == 1 else None


def download_tes3conv():
    LOG("Consultando o GitHub pela versão mais recente do tes3conv ...")
    req = urllib.request.Request(
        TES3CONV_API, headers={"User-Agent": "PFP-PTBR", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            rel = json.load(r)
    except Exception as e:
        raise PFPError(
            f"Não consegui acessar o GitHub ({e}).\n"
            "Baixe o tes3conv manualmente em\n"
            "https://github.com/Greatness7/tes3conv/releases\n"
            f"e coloque o tes3conv.exe em: {app_dir()}")

    asset = pick_asset(rel.get("assets", []))
    if not asset:
        raise PFPError("Nenhum arquivo compatível no release do tes3conv. "
                       "Baixe manualmente pela página de releases.")
    LOG(f"Baixando {asset['name']} ({rel.get('tag_name', '?')}) ...")
    dest_dir = tools_dir()
    tmp_file = dest_dir / asset["name"]
    req = urllib.request.Request(asset["browser_download_url"],
                                 headers={"User-Agent": "PFP-PTBR"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp_file, "wb") as f:
        shutil.copyfileobj(r, f)

    exe_name = "tes3conv.exe" if IS_WIN else "tes3conv"
    target = dest_dir / exe_name
    if tmp_file.suffix.lower() == ".zip":
        with zipfile.ZipFile(tmp_file) as z:
            member = next((m for m in z.namelist()
                           if Path(m).name.lower() == exe_name.lower()), None)
            if not member:
                raise PFPError("O zip baixado não contém o tes3conv.")
            with z.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
        tmp_file.unlink(missing_ok=True)
    elif tmp_file != target:
        shutil.move(str(tmp_file), str(target))
    if not IS_WIN:
        target.chmod(target.stat().st_mode | stat.S_IEXEC)
    LOG("tes3conv instalado.")
    return str(target)


def ensure_tes3conv():
    exe = find_tes3conv()
    if exe:
        LOG(f"tes3conv encontrado: {exe}")
        return exe
    return download_tes3conv()


# ---------------------------------------------------------------- utilidades
def find_ci(folder, name):
    for p in Path(folder).iterdir():
        if p.name.lower() == name.lower():
            return p
    return None


def run_tes3conv(exe, src, dst, compact=False):
    cmd = [exe] + (["-c"] if compact else []) + ["-o", str(src), str(dst)]
    res = subprocess.run(cmd, capture_output=True, text=True,
                         stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    if res.returncode != 0:
        raise PFPError(f"tes3conv falhou ao converter {src}:\n{res.stderr or res.stdout}")


def load(path):
    LOG(f"  lendo {Path(path).name} ...")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ análise
def index_translation(json_paths):
    idx = {}
    for path in json_paths:
        records = load(path)
        topic = None
        for r in records:
            kind = r.get("type")
            if kind == "Dialogue":
                topic = r["id"]
            elif kind == "DialogueInfo":
                idx[r["id"]] = {
                    "topic": topic,
                    "text": r.get("text"),
                    "fields": {k: r.get(k, "") for k in SPEAKER_FIELDS},
                }
        del records
        gc.collect()
    LOG(f"  respostas na tradução: {len(idx)}")
    return idx


def build_topic_map(pfp, trans):
    votes = defaultdict(Counter)
    topic = None
    topic_type = None
    for r in pfp:
        kind = r.get("type")
        if kind == "Dialogue":
            topic = r["id"]
            topic_type = r.get("dialogue_type")
        elif kind == "DialogueInfo" and topic_type == "Topic":
            t = trans.get(r["id"])
            if t and t["topic"]:
                votes[topic.lower()][t["topic"]] += 1

    topic_map = {}
    for en, counter in votes.items():
        if len(counter) == 1:
            topic_map[en] = next(iter(counter))
    used = set(topic_map.values())

    conflicts = []
    for en, counter in votes.items():
        if en in topic_map:
            continue
        ranked = counter.most_common()
        top_n = ranked[0][1]
        tops = [name for name, n in ranked if n == top_n]
        if len(tops) > 1:
            free = [n for n in tops if n not in used] or tops
            best = max(free, key=lambda n: SequenceMatcher(
                None, en, n.lower()).ratio())
        else:
            best = tops[0]
        topic_map[en] = best
        conflicts.append((en, dict(counter), best))
    return topic_map, conflicts


def build_cell_map(pfp, trans):
    votes = defaultdict(Counter)
    for r in pfp:
        if r.get("type") != "DialogueInfo":
            continue
        t = trans.get(r["id"])
        if not t:
            continue
        a = r.get("speaker_cell", "")
        b = t["fields"]["speaker_cell"]
        if (a and b and a.lower() != b.lower() and "," in a and "," in b
                and a.split(",")[0].strip().lower()
                == b.split(",")[0].strip().lower()):
            votes[a.lower()][b] += 1
    return {a: c.most_common(1)[0][0] for a, c in votes.items()}


def fix_script(text, topic_map, unmapped):
    def repl(m):
        name = m.group(2)
        new = topic_map.get(name.lower())
        if new is None:
            unmapped[name] += 1
            return m.group(0)
        return f'{m.group(1)}"{new}"'
    return ADDTOPIC_RE.sub(repl, text)


def translate_patch(pfp, trans):
    topic_map, conflicts = build_topic_map(pfp, trans)
    cell_map = build_cell_map(pfp, trans)
    LOG(f"  tópicos mapeados: {len(topic_map)}; "
        f"células renomeadas: {len(cell_map)}")

    stats = Counter()
    unmapped_addtopic = Counter()
    unmapped_topics = Counter()
    field_diffs = Counter()
    topic_type = None

    for r in pfp:
        kind = r.get("type")

        if kind == "Dialogue":
            topic_type = r.get("dialogue_type")
            if topic_type == "Topic":
                new = topic_map.get(r["id"].lower())
                if new is None:
                    unmapped_topics[r["id"]] += 1
                elif new != r["id"]:
                    r["id"] = new
                    stats["topicos_renomeados"] += 1

        elif kind == "DialogueInfo":
            cell_new = cell_map.get(r.get("speaker_cell", "").lower())
            if cell_new:
                r["speaker_cell"] = cell_new
                stats["celulas_ajustadas"] += 1
            t = trans.get(r["id"])
            if t is None:
                stats["respostas_so_do_patch"] += 1
            else:
                if t["text"] is not None and r.get("text") != t["text"]:
                    r["text"] = t["text"]
                    stats["textos_trocados"] += 1
                for k in SPEAKER_FIELDS:
                    a, b = r.get(k, ""), t["fields"][k]
                    if a != b:
                        field_diffs[(k, a, b)] += 1
            if r.get("script_text"):
                before = r["script_text"]
                r["script_text"] = fix_script(before, topic_map,
                                              unmapped_addtopic)
                if r["script_text"] != before:
                    stats["scripts_de_resposta_corrigidos"] += 1

        elif kind == "Script":
            for key in ("text", "script_text"):
                if isinstance(r.get(key), str):
                    before = r[key]
                    r[key] = fix_script(before, topic_map, unmapped_addtopic)
                    if r[key] != before:
                        stats["scripts_corrigidos"] += 1

    return {
        "stats": stats, "topic_map": topic_map, "conflicts": conflicts,
        "cell_map": cell_map, "unmapped_addtopic": unmapped_addtopic,
        "unmapped_topics": unmapped_topics, "field_diffs": field_diffs,
    }


def write_reports(out_dir, res):
    with open(out_dir / "relatorio.txt", "w", encoding="utf-8") as f:
        f.write("== Resumo ==\n")
        for k, v in res["stats"].items():
            f.write(f"{k}: {v}\n")
        f.write(f"topicos_mapeados: {len(res['topic_map'])}\n\n")
        f.write("== AddTopic sem mapeamento (ficaram em inglês) ==\n")
        for name, n in res["unmapped_addtopic"].most_common():
            f.write(f"{n:5d}  {name}\n")
        f.write("\n== Tópicos do patch sem equivalente na tradução ==\n")
        for name, n in res["unmapped_topics"].most_common():
            f.write(f"{n:5d}  {name}\n")
        f.write("\n== Tópicos com mais de um nome traduzido (escolhido) ==\n")
        for en, c, best in res["conflicts"]:
            f.write(f"{en}: {c} -> {best}\n")
        f.write("\n== Células renomeadas (patch -> tradução) ==\n")
        for a, b in res["cell_map"].items():
            f.write(f"{a} -> {b}\n")
    with open(out_dir / "mapa_topicos.txt", "w", encoding="utf-8") as f:
        for en, pt in sorted(res["topic_map"].items()):
            if en != pt.lower():
                f.write(f"{en} -> {pt}\n")


# ------------------------------------------------------- detecção da instalação
def steam_libraries():
    libs = []
    roots = []
    if IS_WIN:
        try:
            import winreg
            for hive, sub in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        for val in ("SteamPath", "InstallPath"):
                            try:
                                roots.append(Path(winreg.QueryValueEx(k, val)[0]))
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        roots += [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]
    else:
        home = Path.home()
        roots += [home / ".local/share/Steam", home / ".steam/steam"]
    for root in roots:
        libs.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            try:
                for m in re.finditer(r'"path"\s+"([^"]+)"',
                                     vdf.read_text(encoding="utf-8", errors="ignore")):
                    libs.append(Path(m.group(1).replace("\\\\", "\\")))
            except OSError:
                pass
    return libs


def guess_data_files():
    candidates = [lib / "steamapps/common/Morrowind/Data Files" for lib in steam_libraries()]
    if IS_WIN:
        candidates += [Path(r"C:\GOG Games\Morrowind\Data Files"),
                       Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Morrowind\Data Files"),
                       Path(r"C:\Program Files (x86)\Bethesda Softworks\Morrowind\Data Files")]
    for c in candidates:
        try:
            if c.is_dir() and find_ci(c, "Morrowind.esm"):
                return c
        except OSError:
            continue
    return None


# ---------------------------------------------------------------- pipeline
def run_pipeline(patch_path, trad_dir, instalar, out_dir, keep_json=False):
    exe = ensure_tes3conv()

    trad_dir = Path(trad_dir)
    patch = Path(patch_path)
    if not trad_dir.is_dir():
        raise PFPError(f"Pasta da tradução não encontrada: {trad_dir}")
    if not patch.is_file():
        raise PFPError(f"Patch não encontrado: {patch}")

    backup = patch.with_name(patch.name + ".original")
    source = backup if backup.is_file() else patch

    out_dir = Path(out_dir)
    if out_dir.resolve() == patch.parent.resolve():
        raise PFPError("A pasta de saída não pode ser a mesma do patch original.")
    out_dir.mkdir(parents=True, exist_ok=True)

    masters = [p for p in (find_ci(trad_dir, m) for m in MASTERS) if p]
    if not any(p.name.lower() == "morrowind.esm" for p in masters):
        raise PFPError(f"Morrowind.esm não encontrado em {trad_dir}")

    tmp_ctx = None
    if keep_json:
        tmp = out_dir / "json"
        tmp.mkdir(exist_ok=True)
    else:
        tmp_ctx = tempfile.TemporaryDirectory(prefix="pfp_ptbr_")
        tmp = Path(tmp_ctx.name)

    try:
        LOG("\n[1/4] Convertendo arquivos para JSON ...")
        json_masters = []
        for m in masters:
            dst = tmp / (m.stem.lower() + ".json")
            LOG(f"  {m.name}")
            run_tes3conv(exe, m, dst, compact=True)
            json_masters.append(dst)
        pfp_json = tmp / "pfp.json"
        LOG(f"  {source.name}")
        run_tes3conv(exe, source, pfp_json, compact=True)

        LOG("\n[2/4] Lendo a tradução ...")
        trans = index_translation(json_masters)

        LOG("\n[3/4] Traduzindo o patch ...")
        pfp = load(pfp_json)
        res = translate_patch(pfp, trans)
        out_json = tmp / "pfp_ptbr.json"
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(pfp, f, ensure_ascii=False, separators=(",", ":"))
        del pfp
        gc.collect()

        LOG("\n[4/4] Gerando o plugin ...")
        out_esm = out_dir / patch.name
        run_tes3conv(exe, out_json, out_esm)
        write_reports(out_dir, res)
    finally:
        if tmp_ctx:
            tmp_ctx.cleanup()

    LOG("\nPronto.")
    for k, v in res["stats"].items():
        LOG(f"  {k}: {v}")
    LOG(f"  AddTopic sem mapeamento: {len(res['unmapped_addtopic'])}")
    LOG(f"  tópicos sem equivalente: {len(res['unmapped_topics'])}")

    if instalar:
        if not backup.exists():
            shutil.copy2(patch, backup)
        shutil.copy2(out_esm, patch)
        LOG(f"\nInstalado: {patch}")
        LOG(f"Original guardado em: {backup}")
        LOG("Para desfazer: apague o patch e renomeie o arquivo .original de volta.")
    else:
        LOG(f"\nPlugin gerado: {out_esm}")
        LOG("Para usar: faça backup do Patch for Purists.esm original e "
            "coloque este arquivo no lugar dele (mesmo nome).")
    LOG(f"Relatórios: {out_dir}")
    return out_dir


# ------------------------------------------------------------------ interface
BG = "#16110d"        # fundo (couro escuro)
PANEL = "#241b14"     # painéis
EDGE = "#6b5230"      # bordas bronze
GOLD = "#dfc99a"      # texto principal (pergaminho)
GOLD_DIM = "#a08c64"
RED = "#7a2b1e"       # botão (sangue seco)
RED_HOT = "#9c3a28"
FONT_TITLE = ("Palatino Linotype", 20, "bold")
FONT_BODY = ("Palatino Linotype", 11)
FONT_SMALL = ("Palatino Linotype", 9, "italic")
FONT_LOG = ("Consolas", 9)


class MWButton(tk.Label):
    def __init__(self, master, text, command, big=False, **kw):
        super().__init__(master, text=text, bg=RED if big else PANEL, fg=GOLD,
                         font=("Palatino Linotype", 14 if big else 10, "bold"),
                         padx=18 if big else 10, pady=8 if big else 3,
                         highlightthickness=2, highlightbackground=EDGE,
                         cursor="hand2", **kw)
        self._cmd, self._big, self._enabled = command, big, True
        self.bind("<Enter>", lambda e: self._paint(True))
        self.bind("<Leave>", lambda e: self._paint(False))
        self.bind("<Button-1>", lambda e: self._enabled and self._cmd())

    def _paint(self, hover):
        if not self._enabled:
            return
        base = RED if self._big else PANEL
        hot = RED_HOT if self._big else "#33271b"
        self.configure(bg=hot if hover else base)

    def set_enabled(self, enabled):
        self._enabled = enabled
        self.configure(fg=GOLD if enabled else GOLD_DIM,
                       cursor="hand2" if enabled else "arrow")
        self._paint(False)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.configure(bg=BG)
        self.geometry("760x680")
        self.minsize(680, 600)
        self.q = queue.Queue()
        self.busy = False

        self.var_patch = tk.StringVar()
        self.var_trad = tk.StringVar()
        self.var_inst = tk.BooleanVar(value=True)

        self._build()
        self._autodetect()
        self.after(100, self._pump)

    # ---- layout
    def _build(self):
        tk.Label(self, text="◆ ═══════ ◆ ═══════ ◆", bg=BG, fg=EDGE,
                 font=("Palatino Linotype", 12)).pack(pady=(14, 0))
        tk.Label(self, text="Patch for Purists", bg=BG, fg=GOLD,
                 font=("Palatino Linotype", 26, "bold")).pack()
        tk.Label(self, text="Tradução para o Português do Brasil", bg=BG, fg=GOLD,
                 font=("Palatino Linotype", 14, "italic")).pack()
        tk.Label(self, text="◆ ═══════ ◆ ═══════ ◆", bg=BG, fg=EDGE,
                 font=("Palatino Linotype", 12)).pack(pady=(0, 6))
        tk.Label(self,
                 text="“Bem-vindo a Vvardenfell, forasteiro. Aponte o patch e a sua tradução, "
                      "e os tópicos de diálogo voltarão a se entender.”",
                 bg=BG, fg=GOLD_DIM, font=FONT_SMALL, wraplength=640,
                 justify="center").pack(pady=(0, 10))

        box = tk.Frame(self, bg=PANEL, highlightthickness=2, highlightbackground=EDGE)
        box.pack(fill="x", padx=24)
        self._row(box, "Patch for Purists.esm (original, em inglês)", self.var_patch,
                  self._pick_patch)
        self._row(box, "Pasta Data Files com o Morrowind traduzido", self.var_trad,
                  self._pick_trad)

        chk = tk.Checkbutton(box, text="Instalar direto (guarda o original como “.original”)",
                             variable=self.var_inst, bg=PANEL, fg=GOLD,
                             selectcolor=BG, activebackground=PANEL, activeforeground=GOLD,
                             font=FONT_BODY, bd=0, highlightthickness=0)
        chk.pack(anchor="w", padx=14, pady=(2, 12))

        self.btn = MWButton(self, "⚔  Traduzir o Patch", self._start, big=True)
        self.btn.pack(pady=14)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("MW.Horizontal.TProgressbar", troughcolor=PANEL, background="#b08a3e",
                        bordercolor=EDGE, lightcolor="#b08a3e", darkcolor="#7d5f26")
        self.bar = ttk.Progressbar(self, style="MW.Horizontal.TProgressbar",
                                   mode="indeterminate", length=300)
        self.bar.pack(fill="x", padx=24)

        logf = tk.Frame(self, bg=PANEL, highlightthickness=2, highlightbackground=EDGE)
        logf.pack(fill="both", expand=True, padx=24, pady=(10, 4))
        self.log = tk.Text(logf, bg="#0f0b08", fg=GOLD, font=FONT_LOG, wrap="word",
                           bd=0, padx=8, pady=6, state="disabled", insertbackground=GOLD)
        sb = tk.Scrollbar(logf, command=self.log.yview, bg=PANEL, troughcolor=BG)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", padx=24, pady=(2, 10))
        link = tk.Label(foot, text="Página do mod no Nexus", bg=BG, fg=GOLD_DIM,
                        font=("Palatino Linotype", 9, "underline"), cursor="hand2")
        link.pack(side="left")
        link.bind("<Button-1>", lambda e: webbrowser.open(NEXUS_URL))
        MWButton(foot, "Abrir pasta de saída",
                 lambda: self._open_out()).pack(side="right")

    def _row(self, parent, label, var, cmd):
        tk.Label(parent, text=label, bg=PANEL, fg=GOLD, font=FONT_BODY).pack(
            anchor="w", padx=14, pady=(12, 2))
        line = tk.Frame(parent, bg=PANEL)
        line.pack(fill="x", padx=14)
        ent = tk.Entry(line, textvariable=var, bg="#0f0b08", fg=GOLD, font=FONT_BODY,
                       insertbackground=GOLD, relief="flat", highlightthickness=1,
                       highlightbackground=EDGE, highlightcolor=GOLD_DIM)
        ent.pack(side="left", fill="x", expand=True, ipady=4)
        MWButton(line, "Procurar…", cmd).pack(side="left", padx=(8, 0))

    # ---- ações
    def _autodetect(self):
        g = guess_data_files()
        if g:
            self.var_trad.set(str(g))
            self._log(f"Morrowind encontrado em: {g}")
            p = find_ci(g, "Patch for Purists.esm")
            if p:
                self.var_patch.set(str(p))
        else:
            self._log("Não achei o Morrowind automaticamente; escolha a pasta Data Files.")
        self._log("O tes3conv será baixado automaticamente do GitHub, se necessário.\n")

    def _pick_patch(self):
        p = filedialog.askopenfilename(
            title="Escolha o Patch for Purists.esm",
            filetypes=[("Plugins do Morrowind", "*.esm *.esp"), ("Todos", "*.*")])
        if p:
            self.var_patch.set(p)

    def _pick_trad(self):
        p = filedialog.askdirectory(title="Escolha a pasta Data Files do Morrowind traduzido")
        if p:
            self.var_trad.set(p)

    def _open_out(self):
        d = app_dir() / "saida"
        d.mkdir(exist_ok=True)
        if IS_WIN:
            os.startfile(d)  # noqa
        else:
            subprocess.Popen(["xdg-open", str(d)])

    def _log(self, s):
        self.log.configure(state="normal")
        self.log.insert("end", s + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _start(self):
        if self.busy:
            return
        patch, trad = self.var_patch.get().strip().strip('"'), self.var_trad.get().strip().strip('"')
        if not patch or not trad:
            messagebox.showwarning(APP_TITLE, "Informe o patch e a pasta Data Files.")
            return
        if self.var_inst.get() and not messagebox.askyesno(
                APP_TITLE, "O Patch for Purists.esm será substituído pela versão traduzida.\n"
                           "O original ficará guardado como “.original”. Continuar?"):
            return
        self.busy = True
        self.btn.set_enabled(False)
        self.bar.start(12)
        inst = self.var_inst.get()
        threading.Thread(target=self._work, args=(patch, trad, inst), daemon=True).start()

    def _work(self, patch, trad, inst):
        global LOG
        LOG = lambda s: self.q.put(("log", str(s)))
        try:
            out = run_pipeline(patch, trad, inst, app_dir() / "saida")
            self.q.put(("done", "Tradução concluída! Veja o relatório na pasta “saida”."))
        except PFPError as e:
            self.q.put(("log", f"\nERRO: {e}"))
            self.q.put(("error", str(e)))
        except Exception as e:  # noqa
            self.q.put(("log", f"\nERRO inesperado: {e!r}"))
            self.q.put(("error", f"Erro inesperado: {e!r}"))

    def _pump(self):
        try:
            while True:
                kind, msg = self.q.get_nowait()
                if kind == "log":
                    self._log(msg)
                else:
                    self.bar.stop()
                    self.busy = False
                    self.btn.set_enabled(True)
                    (messagebox.showinfo if kind == "done" else messagebox.showerror)(APP_TITLE, msg)
        except queue.Empty:
            pass
        self.after(100, self._pump)


if __name__ == "__main__":
    App().mainloop()

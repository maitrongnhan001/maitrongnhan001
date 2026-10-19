#!/usr/bin/env python3
"""Scan every repository owned by the user (public + private) and rewrite the
Tech Stack section of README.md between the TECH_STACK markers.

Detection sources per repo:
  * GitHub language stats
  * Dependency manifests (package.json, requirements.txt, composer.json, pom.xml,
    build.gradle, go.mod, Cargo.toml, Gemfile, pubspec.yaml, pyproject.toml, ...)
  * Well-known files (Dockerfile, docker-compose, *.tf, k8s manifests, workflows)

Env: GH_TOKEN (PAT with `repo` scope to include private repos), GH_USER.
Only the Python standard library is used.
"""
import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

TOKEN = os.environ["GH_TOKEN"]
USER = os.environ.get("GH_USER", "maitrongnhan001")
README = os.environ.get("README_PATH", "README.md")
START, END = "<!--TECH_STACK_START-->", "<!--TECH_STACK_END-->"
INCLUDE_FORKS = os.environ.get("INCLUDE_FORKS", "false").lower() == "true"
INCLUDE_ARCHIVED = os.environ.get("INCLUDE_ARCHIVED", "true").lower() == "true"
MAX_MANIFESTS_PER_REPO = 25

# keyword (lowercase, matched against dependency names) -> (label, simple-icons slug, hex color, category)
TECH = {
    # Frontend
    "react": ("React", "react", "61DAFB", "Frontend"),
    "next": ("Next.js", "nextdotjs", "000000", "Frontend"),
    "vue": ("Vue.js", "vuedotjs", "4FC08D", "Frontend"),
    "nuxt": ("Nuxt", "nuxtdotjs", "00DC82", "Frontend"),
    "@angular/core": ("Angular", "angular", "DD0031", "Frontend"),
    "svelte": ("Svelte", "svelte", "FF3E00", "Frontend"),
    "jquery": ("jQuery", "jquery", "0769AD", "Frontend"),
    "tailwindcss": ("Tailwind CSS", "tailwindcss", "06B6D4", "Frontend"),
    "bootstrap": ("Bootstrap", "bootstrap", "7952B3", "Frontend"),
    "sass": ("Sass", "sass", "CC6699", "Frontend"),
    "redux": ("Redux", "redux", "764ABC", "Frontend"),
    "vite": ("Vite", "vite", "646CFF", "Frontend"),
    "webpack": ("Webpack", "webpack", "8DD6F9", "Frontend"),
    "@mui/material": ("MUI", "mui", "007FFF", "Frontend"),
    "antd": ("Ant Design", "antdesign", "0170FE", "Frontend"),
    "react-native": ("React Native", "react", "20232A", "Mobile"),
    "expo": ("Expo", "expo", "000020", "Mobile"),
    "flutter": ("Flutter", "flutter", "02569B", "Mobile"),
    # Backend
    "express": ("Express", "express", "000000", "Backend"),
    "@nestjs/core": ("NestJS", "nestjs", "E0234E", "Backend"),
    "fastify": ("Fastify", "fastify", "000000", "Backend"),
    "koa": ("Koa", "koa", "33333D", "Backend"),
    "socket.io": ("Socket.IO", "socketdotio", "010101", "Backend"),
    "graphql": ("GraphQL", "graphql", "E10098", "Backend"),
    "apollo": ("Apollo", "apollographql", "311C87", "Backend"),
    "django": ("Django", "django", "092E20", "Backend"),
    "flask": ("Flask", "flask", "000000", "Backend"),
    "fastapi": ("FastAPI", "fastapi", "009688", "Backend"),
    "celery": ("Celery", "celery", "37814A", "Backend"),
    "laravel/framework": ("Laravel", "laravel", "FF2D20", "Backend"),
    "symfony": ("Symfony", "symfony", "000000", "Backend"),
    "codeigniter": ("CodeIgniter", "codeigniter", "EF4223", "Backend"),
    "spring-boot": ("Spring Boot", "springboot", "6DB33F", "Backend"),
    "springframework": ("Spring", "spring", "6DB33F", "Backend"),
    "hibernate": ("Hibernate", "hibernate", "59666C", "Backend"),
    "gin-gonic": ("Gin", "gin", "00ADD8", "Backend"),
    "rails": ("Rails", "rubyonrails", "D30001", "Backend"),
    "grpc": ("gRPC", "grpc", "244C5A", "Backend"),
    "rabbitmq": ("RabbitMQ", "rabbitmq", "FF6600", "Backend"),
    "amqplib": ("RabbitMQ", "rabbitmq", "FF6600", "Backend"),
    "kafka": ("Kafka", "apachekafka", "231F20", "Backend"),
    "bullmq": ("BullMQ", "redis", "DC382D", "Backend"),
    "passport": ("Passport", "passport", "34E27A", "Backend"),
    "jsonwebtoken": ("JWT", "jsonwebtokens", "000000", "Backend"),
    # Databases / ORM
    "mongoose": ("MongoDB", "mongodb", "47A248", "Database"),
    "mongodb": ("MongoDB", "mongodb", "47A248", "Database"),
    "pymongo": ("MongoDB", "mongodb", "47A248", "Database"),
    "mysql": ("MySQL", "mysql", "4479A1", "Database"),
    "pg": ("PostgreSQL", "postgresql", "4169E1", "Database"),
    "postgres": ("PostgreSQL", "postgresql", "4169E1", "Database"),
    "psycopg": ("PostgreSQL", "postgresql", "4169E1", "Database"),
    "sqlite": ("SQLite", "sqlite", "003B57", "Database"),
    "redis": ("Redis", "redis", "DC382D", "Database"),
    "ioredis": ("Redis", "redis", "DC382D", "Database"),
    "elasticsearch": ("Elasticsearch", "elasticsearch", "005571", "Database"),
    "prisma": ("Prisma", "prisma", "2D3748", "Database"),
    "typeorm": ("TypeORM", "typeorm", "FE0803", "Database"),
    "sequelize": ("Sequelize", "sequelize", "52B0E7", "Database"),
    "sqlalchemy": ("SQLAlchemy", "sqlalchemy", "D71F00", "Database"),
    "firebase": ("Firebase", "firebase", "FFCA28", "Database"),
    "supabase": ("Supabase", "supabase", "3FCF8E", "Database"),
    "cassandra": ("Cassandra", "apachecassandra", "1287B1", "Database"),
    # Testing & tooling
    "jest": ("Jest", "jest", "C21325", "Testing & Tooling"),
    "mocha": ("Mocha", "mocha", "8D6748", "Testing & Tooling"),
    "vitest": ("Vitest", "vitest", "6E9F18", "Testing & Tooling"),
    "cypress": ("Cypress", "cypress", "17202C", "Testing & Tooling"),
    "playwright": ("Playwright", "playwright", "2EAD33", "Testing & Tooling"),
    "selenium": ("Selenium", "selenium", "43B02A", "Testing & Tooling"),
    "pytest": ("Pytest", "pytest", "0A9EDC", "Testing & Tooling"),
    "phpunit": ("PHPUnit", "php", "777BB4", "Testing & Tooling"),
    "junit": ("JUnit", "junit5", "25A162", "Testing & Tooling"),
    "eslint": ("ESLint", "eslint", "4B32C3", "Testing & Tooling"),
    "prettier": ("Prettier", "prettier", "F7B93E", "Testing & Tooling"),
    "storybook": ("Storybook", "storybook", "FF4785", "Testing & Tooling"),
    "swagger": ("Swagger", "swagger", "85EA2D", "Testing & Tooling"),
    # Data / AI
    "tensorflow": ("TensorFlow", "tensorflow", "FF6F00", "Data & AI"),
    "torch": ("PyTorch", "pytorch", "EE4C2C", "Data & AI"),
    "scikit-learn": ("scikit-learn", "scikitlearn", "F7931E", "Data & AI"),
    "pandas": ("Pandas", "pandas", "150458", "Data & AI"),
    "numpy": ("NumPy", "numpy", "013243", "Data & AI"),
    "opencv": ("OpenCV", "opencv", "5C3EE8", "Data & AI"),
    "langchain": ("LangChain", "langchain", "1C3C3C", "Data & AI"),
    "openai": ("OpenAI", "openai", "412991", "Data & AI"),
    "google-genai": ("Gemini", "googlegemini", "8E75B2", "Data & AI"),
    "@google/generative-ai": ("Gemini", "googlegemini", "8E75B2", "Data & AI"),
    # Cloud
    "aws-sdk": ("AWS", "amazonwebservices", "232F3E", "Cloud & DevOps"),
    "boto3": ("AWS", "amazonwebservices", "232F3E", "Cloud & DevOps"),
    "@aws-sdk": ("AWS", "amazonwebservices", "232F3E", "Cloud & DevOps"),
    "@google-cloud": ("Google Cloud", "googlecloud", "4285F4", "Cloud & DevOps"),
    "firebase-admin": ("Firebase", "firebase", "FFCA28", "Database"),
    "azure": ("Azure", "microsoftazure", "0078D4", "Cloud & DevOps"),
    "stripe": ("Stripe", "stripe", "635BFF", "Cloud & DevOps"),
}

# file-name based detection -> (label, slug, color, category)
FILE_TECH = [
    (re.compile(r"(^|/)Dockerfile(\..+)?$|(^|/)docker-compose.*\.ya?ml$"), ("Docker", "docker", "2496ED", "Cloud & DevOps")),
    (re.compile(r"\.tf$"), ("Terraform", "terraform", "844FBA", "Cloud & DevOps")),
    (re.compile(r"(^|/)\.github/workflows/.+\.ya?ml$"), ("GitHub Actions", "githubactions", "2088FF", "Cloud & DevOps")),
    (re.compile(r"(^|/)Jenkinsfile$"), ("Jenkins", "jenkins", "D24939", "Cloud & DevOps")),
    (re.compile(r"(^|/)\.gitlab-ci\.ya?ml$"), ("GitLab CI", "gitlab", "FC6D26", "Cloud & DevOps")),
    (re.compile(r"(^|/)(k8s|kubernetes|helm|charts)/"), ("Kubernetes", "kubernetes", "326CE5", "Cloud & DevOps")),
    (re.compile(r"(^|/)nginx.*\.conf$"), ("Nginx", "nginx", "009639", "Cloud & DevOps")),
    (re.compile(r"(^|/)ansible.*\.ya?ml$"), ("Ansible", "ansible", "EE0000", "Cloud & DevOps")),
    (re.compile(r"(^|/)firebase\.json$"), ("Firebase", "firebase", "FFCA28", "Database")),
    (re.compile(r"(^|/)vercel\.json$"), ("Vercel", "vercel", "000000", "Cloud & DevOps")),
    (re.compile(r"\.(ipynb)$"), ("Jupyter", "jupyter", "F37626", "Data & AI")),
]

LANG_META = {
    "JavaScript": ("javascript", "F7DF1E", "black"),
    "TypeScript": ("typescript", "3178C6", "white"),
    "Python": ("python", "3776AB", "white"),
    "PHP": ("php", "777BB4", "white"),
    "Java": ("openjdk", "ED8B00", "white"),
    "Kotlin": ("kotlin", "7F52FF", "white"),
    "Swift": ("swift", "F05138", "white"),
    "Go": ("go", "00ADD8", "white"),
    "Rust": ("rust", "000000", "white"),
    "C#": ("csharp", "512BD4", "white"),
    "C++": ("cplusplus", "00599C", "white"),
    "C": ("c", "A8B9CC", "black"),
    "Ruby": ("ruby", "CC342D", "white"),
    "Dart": ("dart", "0175C2", "white"),
    "Shell": ("gnubash", "4EAA25", "white"),
    "HTML": ("html5", "E34F26", "white"),
    "CSS": ("css3", "1572B6", "white"),
    "SCSS": ("sass", "CC6699", "white"),
    "Vue": ("vuedotjs", "4FC08D", "white"),
    "Dockerfile": ("docker", "2496ED", "white"),
}

MANIFESTS = re.compile(
    r"(^|/)(package\.json|requirements[^/]*\.txt|Pipfile|pyproject\.toml|composer\.json|"
    r"pom\.xml|build\.gradle(\.kts)?|go\.mod|Cargo\.toml|Gemfile|pubspec\.yaml|"
    r"docker-compose[^/]*\.ya?ml)$"
)
IGNORED_DIRS = re.compile(r"(^|/)(node_modules|vendor|dist|build|\.venv|venv|third_party)/")


def api(path, raw=False):
    url = path if path.startswith("http") else f"https://api.github.com{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tech-stack-scanner",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read().decode("utf-8", "replace")
            return data if raw else json.loads(data)
    except Exception as e:  # keep scanning even if one call fails
        print(f"  ! {url}: {e}", file=sys.stderr)
        return None


def list_repos():
    repos, page = [], 1
    while True:
        batch = api(f"/user/repos?per_page=100&page={page}&affiliation=owner&sort=pushed")
        if not batch:
            break
        repos += batch
        page += 1
    out = []
    for r in repos:
        if r["owner"]["login"].lower() != USER.lower():
            continue
        if r["fork"] and not INCLUDE_FORKS:
            continue
        if r["archived"] and not INCLUDE_ARCHIVED:
            continue
        out.append(r)
    return out


def dep_names(path, text):
    """Return a set of lowercase dependency identifiers found in a manifest."""
    names = set()
    base = path.rsplit("/", 1)[-1]
    try:
        if base == "package.json":
            j = json.loads(text)
            for k in ("dependencies", "devDependencies", "peerDependencies"):
                names |= {n.lower() for n in j.get(k, {})}
        elif base == "composer.json":
            j = json.loads(text)
            for k in ("require", "require-dev"):
                names |= {n.lower() for n in j.get(k, {})}
        elif base.startswith("requirements") or base == "Pipfile" or base == "pyproject.toml":
            for line in text.splitlines():
                m = re.match(r"\s*[\"']?([A-Za-z0-9_.\-]+)", line)
                if m:
                    names.add(m.group(1).lower())
        elif base == "pubspec.yaml":
            names.add("flutter") if "flutter:" in text else None
            names |= {m.lower() for m in re.findall(r"^\s{2}([a-z0-9_]+):", text, re.M)}
        else:  # pom.xml, gradle, go.mod, Cargo.toml, Gemfile, docker-compose
            names |= {t.lower() for t in re.findall(r"[A-Za-z0-9_.@/\-]{2,}", text)}
    except Exception:
        pass
    return names


def match_tech(names):
    found = {}
    for n in names:
        for key, meta in TECH.items():
            if n == key or n.startswith(key + "/") or n.startswith(key + "-") and len(key) > 3 \
               or (key.startswith("@") and n.startswith(key)) or (len(key) > 4 and key in n and "/" not in key and not n.startswith("@types")):
                found[meta[0]] = meta
    return found


def badge(label, slug, color, logo_color="white"):
    lab = urllib.parse.quote(label.replace("-", "--"))
    return f"![{label}](https://img.shields.io/badge/{lab}-{color}?style=flat-square&logo={slug}&logoColor={logo_color})"


def main():
    repos = list_repos()
    print(f"Scanning {len(repos)} repositories for {USER}")
    langs = Counter()
    techs = {}
    usage = Counter()
    for r in repos:
        full = r["full_name"]
        print(f"- {full} ({'private' if r['private'] else 'public'})")
        l = api(f"/repos/{full}/languages") or {}
        for k, v in l.items():
            langs[k] += v
        tree = api(f"/repos/{full}/git/trees/{r['default_branch']}?recursive=1")
        if not tree:
            continue
        paths = [t["path"] for t in tree.get("tree", []) if t["type"] == "blob" and not IGNORED_DIRS.search(t["path"])]
        repo_found = {}
        for p in paths:
            for rx, meta in FILE_TECH:
                if rx.search(p):
                    repo_found[meta[0]] = meta
        manifests = [p for p in paths if MANIFESTS.search(p)][:MAX_MANIFESTS_PER_REPO]
        for p in manifests:
            text = api(f"/repos/{full}/contents/{urllib.parse.quote(p)}?ref={r['default_branch']}", raw=True)
            if text:
                repo_found.update(match_tech(dep_names(p, text)))
        for name, meta in repo_found.items():
            techs[name] = meta
            usage[name] += 1

    total = sum(langs.values()) or 1
    lines = [f"> Auto-generated from **{len(repos)} repositories** (public + private) "
             f"- last scan: `{__import__('datetime').datetime.utcnow():%Y-%m-%d}` UTC.", ""]

    # languages
    top = [(k, v) for k, v in langs.most_common() if v / total >= 0.005]
    if top:
        lines += ["**Languages**", "", "<div align=\"center\">", ""]
        for k, v in top:
            slug, color, lc = LANG_META.get(k, ("code", "555555", "white"))
            lines.append(badge(f"{k} {v / total:.0%}", slug, color, lc))
        lines += ["", "</div>", ""]

    groups = defaultdict(list)
    for name, (label, slug, color, cat) in techs.items():
        groups[cat].append((usage[name], label, slug, color))
    order = ["Frontend", "Mobile", "Backend", "Database", "Data & AI", "Testing & Tooling", "Cloud & DevOps"]
    for cat in order + [c for c in groups if c not in order]:
        if cat not in groups:
            continue
        lines += [f"**{cat}**", "", "<div align=\"center\">", ""]
        for _, label, slug, color in sorted(groups[cat], key=lambda x: (-x[0], x[1])):
            lines.append(badge(label, slug, color))
        lines += ["", "</div>", ""]

    block = "\n".join(lines).rstrip() + "\n"
    with open(README, encoding="utf-8") as f:
        content = f.read()
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pattern.search(content):
        sys.exit(f"Markers {START} / {END} not found in {README}")
    new = pattern.sub(lambda _: f"{START}\n{block}{END}", content)
    if new != content:
        with open(README, "w", encoding="utf-8") as f:
            f.write(new)
        print("README updated")
    else:
        print("No changes")


if __name__ == "__main__":
    main()

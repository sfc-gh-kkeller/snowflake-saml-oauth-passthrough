"""
Skill & Knowledge-to-Zettelkasten indexer.

Two content sources are indexed into the skill knowledge graph:

1. Skill markdown files (skills/*.md) — Behavioral instructions parsed by ## sections.
   These provide how-to and routing knowledge.

2. Knowledge files (knowledge/{skill}/*.knowledge.md) — Structured domain knowledge
   with explicit ontology. Each ## Entry: block becomes a zettel with metadata
   (importance, tags, connects-to) for rich graph relationships.

The separation allows skills to remain pure instructions while knowledge files
hold domain facts optimized for zettelkasten ingestion and semantic retrieval.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import yaml

from .memory_plugin import get_memory_plugin, SKILL_KNOWLEDGE_NAMESPACE
from .skill_loader import SKILLS_DIR

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "knowledge"

# Regex for knowledge entry headers: ## Entry: Title
ENTRY_HEADER_RE = re.compile(r"^##\s+Entry:\s+(.+)$")
YAML_FENCE_START = "```yaml"
YAML_FENCE_END = "```"


def _parse_yaml_block(lines: list[str], start_idx: int) -> tuple[dict | None, int]:
    """Parse a fenced YAML block. Returns (data, end_line_idx)."""
    if start_idx >= len(lines) or lines[start_idx].strip() != YAML_FENCE_START:
        return None, start_idx
    end_idx = start_idx + 1
    body: list[str] = []
    while end_idx < len(lines):
        if lines[end_idx].strip() == YAML_FENCE_END:
            break
        body.append(lines[end_idx])
        end_idx += 1
    try:
        data = yaml.safe_load("\n".join(body))
        if isinstance(data, dict):
            return data, end_idx + 1
    except yaml.YAMLError:
        pass
    return None, end_idx + 1


def parse_knowledge_file(filepath: Path, domain: str) -> list[dict]:
    """Parse a .knowledge.md file into structured entries.

    Each ## Entry: block becomes one entry with metadata from the YAML block.
    Returns list of dicts with: id, title, content, importance, tags,
    connects_to, domain, source_type.
    """
    text = filepath.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Parse file-level frontmatter (--- block at top)
    file_domain = domain
    file_relates_to: list[str] = []
    content_start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                try:
                    frontmatter = yaml.safe_load("\n".join(lines[1:i]))
                    if isinstance(frontmatter, dict):
                        file_domain = frontmatter.get("domain", domain)
                        file_relates_to = frontmatter.get("relates-to", []) or []
                except yaml.YAMLError:
                    pass
                content_start = i + 1
                break

    # Find all ## Entry: blocks
    entry_starts: list[int] = []
    for i in range(content_start, len(lines)):
        if ENTRY_HEADER_RE.match(lines[i]):
            entry_starts.append(i)

    if not entry_starts:
        return []

    entries = []
    for idx, start in enumerate(entry_starts):
        end = entry_starts[idx + 1] if idx + 1 < len(entry_starts) else len(lines)

        # Extract title from header
        m = ENTRY_HEADER_RE.match(lines[start])
        if not m:
            continue
        title = m.group(1).strip()

        # Find YAML metadata block
        yaml_data = None
        for i in range(start + 1, min(start + 12, end)):
            if lines[i].strip() == YAML_FENCE_START:
                yaml_data, yaml_end = _parse_yaml_block(lines, i)
                break

        if not yaml_data:
            # No metadata — still index the content with defaults
            yaml_data = {}
            yaml_end = start + 1

        entry_id = yaml_data.get("id", f"entry-{title.lower().replace(' ', '-')[:40]}")
        importance = float(yaml_data.get("importance", 0.8))
        tags = yaml_data.get("tags", []) or []
        connects_to = yaml_data.get("connects-to", []) or []

        # Content is everything after the YAML block until next entry or --- separator
        content_lines = []
        for i in range(yaml_end, end):
            if lines[i].strip() == "---":
                break
            content_lines.append(lines[i])
        content = "\n".join(content_lines).strip()

        if not content or len(content) < 30:
            continue

        entries.append({
            "id": entry_id,
            "title": title,
            "content": content[:3000],
            "importance": importance,
            "tags": tags,
            "connects_to": connects_to,
            "relates_to": file_relates_to,
            "domain": file_domain,
            "source_type": "knowledge_file",
            "source_file": str(filepath.relative_to(KNOWLEDGE_DIR)),
        })

    return entries


def index_knowledge_files(skill_name: str) -> dict:
    """Index all knowledge files for a skill into the zettelkasten.

    Discovers knowledge/{skill_name}/*.knowledge.md and indexes each
    ## Entry: block as a zettel with explicit connections.

    Returns stats: {entries_indexed, files_found, skill}
    """
    plugin = get_memory_plugin()
    if plugin.name == "none":
        return {"error": "Memory plugin not active", "entries_indexed": 0}

    knowledge_skill_dir = KNOWLEDGE_DIR / skill_name
    if not knowledge_skill_dir.is_dir():
        return {"entries_indexed": 0, "files_found": 0, "skill": skill_name}

    files_found = 0
    entries_indexed = 0
    entry_id_map: dict[str, str] = {}  # entry_id -> zettel_id mapping for connections

    # First pass: index all entries
    all_entries = []
    for kf in sorted(knowledge_skill_dir.glob("*.knowledge.md")):
        files_found += 1
        entries = parse_knowledge_file(kf, skill_name)
        all_entries.extend(entries)

    for entry in all_entries:
        content = f"[{entry['domain']}/{entry['id']}] {entry['title']}\n\n{entry['content']}"

        zettel_tags = set(entry["tags"])
        zettel_tags.add(f"domain:{entry['domain']}")
        zettel_tags.add(f"skill:{skill_name}")
        zettel_tags.add(f"source:knowledge_file")
        zettel_tags.add(f"entry:{entry['id']}")
        # Add relates-to as tags for discoverability
        for rel in entry["relates_to"]:
            zettel_tags.add(f"relates:{rel}")

        result = plugin.add(
            SKILL_KNOWLEDGE_NAMESPACE,
            content,
            tags=zettel_tags,
            importance=entry["importance"],
        )
        if result and "id" in result:
            entry_id_map[entry["id"]] = result["id"]
        entries_indexed += 1

    # Second pass: create explicit connections from connects-to metadata
    if entry_id_map:
        try:
            mem = plugin._get(SKILL_KNOWLEDGE_NAMESPACE)
            for entry in all_entries:
                if entry["id"] not in entry_id_map:
                    continue
                zettel_id = entry_id_map[entry["id"]]
                zettel = mem._zettels.get(zettel_id)
                if not zettel:
                    continue
                for target_entry_id in entry.get("connects_to", []):
                    target_zettel_id = entry_id_map.get(target_entry_id)
                    if target_zettel_id and target_zettel_id != zettel_id:
                        zettel.connections.add(target_zettel_id)
                        # Bidirectional connection
                        target_zettel = mem._zettels.get(target_zettel_id)
                        if target_zettel:
                            target_zettel.connections.add(zettel_id)
            plugin._save(SKILL_KNOWLEDGE_NAMESPACE)
        except Exception as e:
            logger.warning("Failed to create explicit connections: %s", e)

    logger.info("Indexed knowledge files for %s: %d entries from %d files", skill_name, entries_indexed, files_found)
    return {"entries_indexed": entries_indexed, "files_found": files_found, "skill": skill_name}


def _parse_skill_md_sections(filepath: Path, domain: str) -> list[dict]:
    """Parse a skill .md file into indexable sections.

    Splits on ## headings and creates one entry per meaningful section.
    Skips frontmatter and very short sections (<50 chars).
    """
    text = filepath.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Skip YAML frontmatter
    content_start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                content_start = i + 1
                break

    # Split into sections on ## headings
    sections = []
    current_heading = ""
    current_lines: list[str] = []

    for line in lines[content_start:]:
        if line.startswith("## "):
            # Save previous section
            if current_lines and len("\n".join(current_lines).strip()) > 50:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Save last section
    if current_lines and len("\n".join(current_lines).strip()) > 50:
        sections.append((current_heading, "\n".join(current_lines).strip()))

    entries = []
    for heading, content in sections:
        entry_id = f"skill-{domain}-{heading.lower().replace(' ', '-')[:30]}" if heading else f"skill-{domain}-main"
        entries.append({
            "id": entry_id,
            "heading": heading or domain,
            "content": content[:2500],
            "domain": domain,
            "source_type": "skill_md",
        })

    return entries


def index_skill_to_zettel(skill_name: str) -> dict:
    """Index a skill's knowledge into the zettel knowledge graph.

    Only indexes structured knowledge files (knowledge/{skill}/*.knowledge.md).
    Skill .md instruction files are NOT indexed here — they are loaded into
    context via the skill loader when triggered. This keeps the knowledge graph
    clean: only domain facts, not behavioral instructions.

    Returns stats: {entries_indexed, knowledge_entries, knowledge_files, skill}
    """
    plugin = get_memory_plugin()
    if plugin.name == "none":
        return {"error": "Memory plugin not active", "entries_indexed": 0}

    # Clear existing entries for this skill (idempotent re-index)
    _remove_skill_entries(skill_name)

    # Index knowledge files (structured domain knowledge)
    kg_result = index_knowledge_files(skill_name)
    entries_indexed = kg_result.get("entries_indexed", 0)

    if entries_indexed:
        logger.info("Indexed skill %s: %d knowledge entries from %d files",
                    skill_name, entries_indexed, kg_result.get("files_found", 0))

    return {
        "entries_indexed": entries_indexed,
        "knowledge_entries": entries_indexed,
        "knowledge_files": kg_result.get("files_found", 0),
        "skill": skill_name,
    }


def _remove_skill_entries(skill_name: str) -> int:
    """Remove all zettels tagged with a specific skill source."""
    plugin = get_memory_plugin()
    if plugin.name == "none":
        return 0

    tag_to_match = f"skill:{skill_name}"
    try:
        mem = plugin._get(SKILL_KNOWLEDGE_NAMESPACE)
        to_delete = [
            z.id for z in list(mem._zettels.values())
            if tag_to_match in z.tags
        ]
        for zid in to_delete:
            mem.delete(zid)
        if to_delete:
            plugin._save(SKILL_KNOWLEDGE_NAMESPACE)
        return len(to_delete)
    except Exception as e:
        logger.warning("Failed to remove skill entries: %s", e)
        return 0


def search_skill_knowledge(
    query: str,
    *,
    domain: Optional[str] = None,
    limit: int = 5,
    min_score: float = 0.25,
) -> list[dict]:
    """Search the skill knowledge graph for relevant entries.

    Args:
        query: The search query (user question)
        domain: Optional domain filter (skill name)
        limit: Max results to return
        min_score: Minimum similarity score threshold

    Returns:
        List of dicts with: content, score, tags, id
    """
    plugin = get_memory_plugin()
    if plugin.name == "none":
        return []

    results = plugin.search(SKILL_KNOWLEDGE_NAMESPACE, query, limit=limit * 2)

    # Filter by score and optionally by domain
    filtered = []
    for r in results:
        if r.get("score", 0) < min_score:
            continue
        if domain:
            domain_tag = f"domain:{domain}"
            if domain_tag not in r.get("tags", []):
                continue
        filtered.append(r)
        if len(filtered) >= limit:
            break

    return filtered


def get_knowledge_stats() -> dict:
    """Get statistics about the skill knowledge graph."""
    plugin = get_memory_plugin()
    if plugin.name == "none":
        return {"status": "disabled", "total_entries": 0}

    try:
        mem = plugin._get(SKILL_KNOWLEDGE_NAMESPACE)
        zettels = list(mem._zettels.values())
        total = len(zettels)

        # Count by domain/skill
        domains: dict[str, int] = {}
        skills: dict[str, int] = {}
        for z in zettels:
            for tag in z.tags:
                if tag.startswith("domain:"):
                    d = tag[7:]
                    domains[d] = domains.get(d, 0) + 1
                elif tag.startswith("skill:"):
                    s = tag[6:]
                    skills[s] = skills.get(s, 0) + 1

        # Index file size
        persist_path = plugin._persist_path(SKILL_KNOWLEDGE_NAMESPACE)
        size_bytes = persist_path.stat().st_size if persist_path.exists() else 0

        return {
            "status": "active",
            "plugin": plugin.name,
            "total_entries": total,
            "domains": domains,
            "skills": skills,
            "index_size_bytes": size_bytes,
            "connections": sum(len(z.connections) for z in zettels),
        }
    except Exception as e:
        logger.warning("Failed to get knowledge stats: %s", e)
        return {"status": "error", "error": str(e), "total_entries": 0}


def list_knowledge_entries(*, domain: Optional[str] = None, limit: int = 50) -> list[dict]:
    """List indexed knowledge entries, optionally filtered by domain."""
    plugin = get_memory_plugin()
    if plugin.name == "none":
        return []

    try:
        mem = plugin._get(SKILL_KNOWLEDGE_NAMESPACE)
        zettels = sorted(mem._zettels.values(), key=lambda z: z.importance, reverse=True)

        results = []
        for z in zettels:
            if domain:
                if f"domain:{domain}" not in z.tags:
                    continue

            entry_domain = ""
            skill_name = ""
            section_id = ""
            for tag in z.tags:
                if tag.startswith("domain:"):
                    entry_domain = tag[7:]
                elif tag.startswith("skill:"):
                    skill_name = tag[6:]
                elif tag.startswith("section:"):
                    section_id = tag[8:]

            results.append({
                "id": z.id,
                "section_id": section_id,
                "domain": entry_domain,
                "skill": skill_name,
                "content": z.content[:200],
                "importance": z.importance,
                "tags": sorted(z.tags),
                "connections": len(z.connections),
                "access_count": z.access_count,
            })
            if len(results) >= limit:
                break

        return results
    except Exception as e:
        logger.warning("Failed to list knowledge entries: %s", e)
        return []


def clear_all_knowledge() -> int:
    """Clear all entries from the skill knowledge namespace."""
    plugin = get_memory_plugin()
    if plugin.name == "none":
        return 0
    try:
        plugin.delete_all(SKILL_KNOWLEDGE_NAMESPACE)
        return 1
    except Exception as e:
        logger.warning("Failed to clear knowledge: %s", e)
        return 0


def get_knowledge_graph() -> dict:
    """Get graph data (nodes + edges) for visualization."""
    plugin = get_memory_plugin()
    if plugin.name == "none":
        return {"nodes": [], "edges": []}

    try:
        mem = plugin._get(SKILL_KNOWLEDGE_NAMESPACE)
        nodes = []
        edges_set = set()

        for z in mem._zettels.values():
            domain = next((t[7:] for t in z.tags if t.startswith("domain:")), "unknown")
            # Label: prefer entry: tag, then section: tag, then extract title from content
            label = next(
                (t.split(":", 1)[1] for t in z.tags if t.startswith("entry:")),
                next(
                    (t.split(":", 1)[1] for t in z.tags if t.startswith("section:")),
                    None,
                ),
            )
            if not label:
                # Extract title from content header: [domain/id] Title
                first_line = z.content.split("\n")[0] if z.content else ""
                if "] " in first_line:
                    label = first_line.split("] ", 1)[1][:50]
                else:
                    label = z.id[:8]
            # First line of content as summary
            first_line = z.content.split("\n")[0][:120] if z.content else ""
            source = next((t[7:] for t in z.tags if t.startswith("source:")), "unknown")

            nodes.append({
                "id": z.id,
                "domain": domain,
                "label": label,
                "connections": len(z.connections),
                "importance": z.importance,
                "access_count": z.access_count,
                "created_at": z.created_at,
                "source": source,
                "summary": first_line,
                "tags": sorted(t for t in z.tags if not t.startswith("skill:") and not t.startswith("domain:") and not t.startswith("source:")),
            })
            for c in z.connections:
                edge_key = tuple(sorted([z.id, c]))
                edges_set.add(edge_key)

        edges = [{"source": e[0], "target": e[1]} for e in edges_set]
        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        logger.warning("Failed to get knowledge graph: %s", e)
        return {"nodes": [], "edges": []}

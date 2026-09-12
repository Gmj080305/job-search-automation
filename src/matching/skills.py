import re

import yaml


def contains(text, term):
    pattern = rf"(?<![\w+]){re.escape(term)}(?![\w+])"
    return bool(re.search(pattern, str(text), re.IGNORECASE))


class Taxonomy:
    def __init__(self, path="config/keywords.yaml"):
        with open(path, encoding="utf-8") as handle:
            config = yaml.safe_load(handle)

        self.aliases = config["skills"]
        self.categories = {
            name: set(skills)
            for name, skills in config["categories"].items()
        }
        self.role_terms = config["role_terms"]

    def extract(self, text):
        return {
            canonical
            for canonical, aliases in self.aliases.items()
            if any(contains(text, alias) for alias in aliases)
        }

    def groups(self, skills):
        skills = set(skills)
        return {
            name
            for name, members in self.categories.items()
            if skills & members
        }

    def compare(self, candidate, required):
        candidate = set(candidate)
        required = set(required)
        strong = candidate & required
        candidate_groups = self.groups(candidate)

        partial = {
            skill
            for skill in required - strong
            if self.groups({skill}) & candidate_groups
        }
        missing = required - strong - partial

        return {
            "strong": sorted(strong),
            "partial": sorted(partial),
            "missing": sorted(missing),
        }

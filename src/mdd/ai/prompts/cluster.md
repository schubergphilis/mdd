You are organising a set of documentation pages into topic clusters for a directory index.

You will receive a JSON array of objects, each with:
- `path`: the relative file path
- `summary`: a one-sentence description of the page

## Task

Group the pages into logical topic clusters. Each cluster should have a short, descriptive title (2–4 words). Pages that do not clearly belong to any cluster may go into a catch-all cluster titled "Other".

## Output format

Return a JSON array of cluster objects. Each object must have:
- `topic_title`: string — the cluster heading (2–4 words, title case)
- `file_paths`: array of strings — the `path` values for pages in this cluster, in a sensible reading order

Return only the JSON array. No preamble, no explanation, no markdown fences.

## Example output

[
  {
    "topic_title": "Architecture",
    "file_paths": ["Architecture/Platform-Topology.md", "Architecture/Deployment-Pipeline.md"]
  },
  {
    "topic_title": "Process",
    "file_paths": ["Process/Onboarding.md", "Process/Offboarding.md"]
  }
]

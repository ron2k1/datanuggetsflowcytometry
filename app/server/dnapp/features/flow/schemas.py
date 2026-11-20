"""The request body of POST /flow/runs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, StrictBool, StrictFloat

from dnapp.core.filters import Filter


class FlowRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gate_id: str
    pops: list[list[int]]
    groups: list[str] | None = None
    channels: list[str] | None = None
    exclude_channels: list[str] = []
    row_filters: list[Filter] = []
    k: int | None = None
    # the Cluster stage: method "wkmeans" (WCluster's Wkmeans) or "tree" (the hierarchical tree,
    # Whclust cut into k), and center_method, where each nugget sits ("original": on one of its
    # own cells, "mean": on the mean of its cells). Left out, they take GET /config's defaults;
    # the package's check refuses any other value, naming the field. The draws and the weighted
    # k-means starts and rounds (draws, num_init, max_iter) aren't request fields: the app runs
    # the package's defaults, and extra="forbid" refuses them by name
    method: str | None = None
    center_method: str | None = None
    # the Transform stage: "auto" (picked per channel from the cells the run clusters), or a
    # number for every channel, 0 keeping the channels linear; the package's check refuses
    # anything else, a list of numbers too, naming cofactor. StrictFloat
    # takes an integer as a float but not true or false, which a plain float reads as 1 and 0
    cofactor: StrictFloat | str | None = None
    standardize: StrictBool | None = None  # the Scale stage; true or false, not 1 or "yes"
    dn_num1: int | None = None
    dn_num2: int | None = None
    seed: int | None = None
    tsne: bool | None = None
    tsne_perplexity: float | None = None
    tsne_seed: int | None = None
    cells_per_file: int | None = None

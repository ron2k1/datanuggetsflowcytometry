"""The library names datanuggets-flow imports or reaches as attributes, as a literal dict: the
flow's copy of the cross-repo contract. tests/flow/test_flow_boundary.py checks every library import
in the package, the tests, the app and the flow benchmarks against it (3a), and every name in it
against the installed library (3b).

datanuggets 0.1.0a3, the version the locks hold, keeps no FLOW_USES in its tests, so this copy is
the contract. A change that imports a new library name adds it here; one that drops the last import
of a name removes it. Attribute uses such as plot.clusters don't show up as imports, so the
datanuggets.plot entry is kept by hand."""

FLOW_USES = {
    "datanuggets": {
        "DataNuggetWarning",
        "DataNuggets",
        "RDraws",
        "WhclustResult",
        "create_dn",
        "cut_tree",
        "plot",
        "whclust",
        "wkmeans",
        "wmean",
        "wpca",
        "wwcss",
    },
    "datanuggets.colors": {"PARENT_K", "TAB10", "block_parents", "cluster_colors", "tree_parents"},
    "datanuggets.filters": {"RowFilter", "filter_mask", "format_filter", "parse_filter"},
    "datanuggets.plot": {"clusters", "dendrogram", "scores"},
    "datanuggets.projection": {
        "PcaView",
        "component_signs",
        "pca_view",
        "project",
        "tsne_2d",
        "tsne_3d",
    },
}

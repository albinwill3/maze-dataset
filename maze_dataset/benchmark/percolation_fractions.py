"""Benchmarking of how successful maze generation is for various values of percolation"""

import functools
import json
from typing import Any, Callable, Sequence, TypeVar
from pathlib import Path

import numpy as np
from jaxtyping import Float
import matplotlib.pyplot as plt
from muutils.json_serialize import (
    serializable_dataclass,
    SerializableDataclass,
    serializable_field,
    json_serialize,
)
from muutils.dictmagic import dotlist_to_nested_dict, update_with_nested_dict
from muutils.parallel import run_maybe_parallel
from zanj import ZANJ

from maze_dataset import MazeDataset, MazeDatasetConfig
from maze_dataset.generation import LatticeMazeGenerators

SweepReturnType = TypeVar("SweepReturnType")
ParamType = TypeVar("ParamType")
AnalysisFunc = Callable[[MazeDatasetConfig], SweepReturnType]


def dataset_success_fraction(cfg: MazeDatasetConfig) -> float:
    dataset: MazeDataset = MazeDataset.from_config(
        cfg,
        do_download=False,
        load_local=False,
        save_local=False,
        verbose=False,
    )

    return len(dataset) / cfg.n_mazes


ANALYSIS_FUNCS: dict[str, AnalysisFunc] = dict(
    dataset_success_fraction=dataset_success_fraction,
)


def sweep(
    cfg_base: MazeDatasetConfig,
    param_values: list[ParamType],
    param_key: str,
    analyze_func: Callable[[MazeDatasetConfig], SweepReturnType],
) -> list[SweepReturnType]:
    outputs: list[SweepReturnType] = []

    for p in param_values:
        # update the config
        cfg_dict: dict = cfg_base.serialize()
        update_with_nested_dict(
            cfg_dict,
            dotlist_to_nested_dict({param_key: p}),
        )
        cfg_test: MazeDatasetConfig = MazeDatasetConfig.load(cfg_dict)

        outputs.append(analyze_func(cfg_test))

    return outputs


@serializable_dataclass()
class SweepResult(SerializableDataclass):
    configs: list[MazeDatasetConfig] = serializable_field(
        serialization_fn=lambda cfgs: [cfg.serialize() for cfg in cfgs],
        deserialize_fn=lambda cfgs: [MazeDatasetConfig.load(cfg) for cfg in cfgs],
    )
    param_values: list[ParamType] = serializable_field(
        serialization_fn=lambda x: json_serialize(x),
        deserialize_fn=lambda x: x,
        assert_type=False,
    )
    result_values: dict[str, list[SweepReturnType]] = serializable_field(
        serialization_fn=lambda x: json_serialize(x),
        deserialize_fn=lambda x: x,
        assert_type=False,
    )
    param_key: str
    analyze_func: Callable[[MazeDatasetConfig], SweepReturnType] = serializable_field(
        serialization_fn=lambda f: f.__name__,
        deserialize_fn=ANALYSIS_FUNCS.get,
        assert_type=False,
    )

    def save(self, path: str | Path, z: ZANJ | None = None) -> None:
        if z is None:
            z = ZANJ()

        z.save(self, path)

    @classmethod
    def read(cls, path: str | Path, z: ZANJ | None = None) -> "SweepResult":
        if z is None:
            z = ZANJ()

        return z.read(path)

    def configs_by_name(self) -> dict[str, MazeDatasetConfig]:
        "return configs by name"
        return {cfg.name: cfg for cfg in self.configs}

    def configs_by_key(self) -> dict[str, MazeDatasetConfig]:
        "return configs by the key used in `result_values`, which is the filename of the config"
        return {cfg.to_fname(): cfg for cfg in self.configs}

    def configs_shared(self) -> dict[str, Any]:
        "return key: value pairs that are shared across all configs"
        # we know that the configs all have the same keys,
        # so this way of doing it is fine
        config_vals: dict[str, set[Any]] = dict()
        for cfg in self.configs:
            for k, v in cfg.serialize().items():
                if k not in config_vals:
                    config_vals[k] = set()
                config_vals[k].add(json.dumps(v))

        shared_vals: dict[str, Any] = dict()

        cfg_ser: dict = self.configs[0].serialize()
        for k, v in config_vals.items():
            if len(v) == 1:
                shared_vals[k] = cfg_ser[k]

        return shared_vals

    def configs_differing_keys(self) -> set[str]:
        "return keys that differ across configs"
        shared_vals: dict[str, Any] = self.configs_shared()
        differing_keys: set[str] = set()

        for k in MazeDatasetConfig.__dataclass_fields__.keys():
            if k not in shared_vals:
                differing_keys.add(k)

        return differing_keys
    

    def configs_value_set(self, key: str) -> list[Any]:
        "return a list of the unique values for a given key"
        d: dict[str, Any] = {
            json.dumps(json_serialize(getattr(cfg, key))): getattr(cfg, key)
            for cfg in self.configs
        }

        return list(d.values())

    def get_where(self, key: str, val_check: Callable[[Any], bool]) -> "SweepResult":
        "get a subset of this `Result` where the configs has `key` satisfying `val_check`"
        configs_list: list[MazeDatasetConfig] = [
            cfg for cfg in self.configs if val_check(getattr(cfg, key))
        ]
        configs_keys: set[str] = {cfg.to_fname() for cfg in configs_list}
        result_values: dict[str, np.ndarray] = {
            k: self.result_values[k] for k in configs_keys
        }

        return SweepResult(
            configs=configs_list,
            param_values=self.param_values,
            result_values=result_values,
            param_key=self.param_key,
            analyze_func=self.analyze_func,
        )

    @classmethod
    def analyze(
        cls,
        configs: list[MazeDatasetConfig],
        param_values: list[ParamType],
        param_key: str,
        analyze_func: Callable[[MazeDatasetConfig], SweepReturnType],
        parallel: bool | int = False,
    ) -> "SweepResult":
        """Analyze success rate of maze generation for different percolation values

        # Parameters:
        - `configs : list[MazeDatasetConfig]`
        configs to try
        - `param_values : np.ndarray`
        numpy array of values to try

        # Returns:
        - `SweepResult`
        """
        n_pvals: int = len(param_values)

        result_values_list: list[float] = run_maybe_parallel(
            func=functools.partial(
                sweep,
                param_values=param_values,
                param_key=param_key,
                analyze_func=analyze_func,
            ),
            iterable=configs,
            keep_ordered=True,
            parallel=parallel,
            pbar_kwargs=dict(total=len(configs)),
        )
        result_values: dict[str, Float[np.ndarray, "n_pvals"]] = {
            cfg.to_fname(): np.array(res)
            for cfg, res in zip(configs, result_values_list)
        }
        return cls(
            configs=configs,
            param_values=param_values,
            result_values=result_values,
            param_key=param_key,
            analyze_func=analyze_func,
        )

    def plot(
        self,
        save_path: str = None,
        cfg_keys: list[str] | None = None,
        cmap_name: str | None = "viridis",
        plot_only: bool = False,
        show: bool = True,
        ax: plt.Axes | None = None,
    ) -> plt.Axes:
        """Plot the results of percolation analysis"""
        # set up figure
        if not ax:
            fig: plt.Figure
            ax: plt.Axes
            fig, ax = plt.subplots(1, 1, figsize=(22, 10))

        # plot
        cmap = plt.get_cmap(cmap_name)
        n_cfgs: int = len(self.result_values)
        for i, (ep_cfg_name, result_values) in enumerate(self.result_values.items()):
            ax.plot(
                self.param_values,
                result_values,
                ".-",
                label=self.configs_by_key()[ep_cfg_name].name,
                color=cmap((i + 0.5) / (n_cfgs - 0.5)),
            )

        # repr of config
        cfg_shared: dict = self.configs_shared()
        cfg_repr: str = (
            str(cfg_shared)
            if cfg_keys is None
            else (
                "MazeDatasetConfig("
                + ", ".join(
                    [
                        f"{k}={cfg_shared[k].__name__}"
                        if isinstance(cfg_shared[k], Callable)
                        else f"{k}={cfg_shared[k]}"
                        for k in cfg_keys
                    ]
                )
                + ")"
            )
        )

        # add title and stuff
        if not plot_only:
            ax.set_xlabel(self.param_key)
            ax.set_ylabel(self.analyze_func.__name__)
            ax.set_title(
                f"{self.param_key} vs {self.analyze_func.__name__}\n{cfg_repr}"
            )
            ax.grid(True)
            ax.legend(loc="lower center")

        # save and show
        if save_path:
            plt.savefig(save_path)

        if show:
            plt.show()

        return ax


DEFAULT_ENDPOINT_KWARGS: list[tuple[str, dict]] = [
    (
        "any",
        dict(deadend_start=False, deadend_end=False, except_on_no_valid_endpoint=False),
    ),
    (
        "deadends",
        dict(deadend_start=True, deadend_end=True, except_on_no_valid_endpoint=False),
    ),
    (
        "deadends_unique",
        dict(
            deadend_start=True,
            deadend_end=True,
            endpoints_not_equal=False,
            except_on_no_valid_endpoint=False,
        ),
    ),
]


def full_analysis(
    n_mazes: int,
    p_val_count: int,
    grid_sizes: list[int],
    ep_kwargs: list[tuple[str, dict]] | None = None,
    generators: Sequence[Callable] = (
        LatticeMazeGenerators.gen_percolation,
        LatticeMazeGenerators.gen_dfs_percolation,
    ),
    save_dir: Path = Path("../docs/benchmarks/percolation_fractions"),
) -> None:
    if ep_kwargs is None:
        ep_kwargs = DEFAULT_ENDPOINT_KWARGS

    # configs
    configs: list[MazeDatasetConfig] = list()

    for ep_kw_name, ep_kw in ep_kwargs:
        for gf_idx, gen_func in enumerate(generators):
            configs.extend(
                [
                    MazeDatasetConfig(
                        name=f"g{grid_n}-{gen_func.__name__.removeprefix('gen_').removesuffix('olation')}",
                        grid_n=grid_n,
                        n_mazes=n_mazes,
                        maze_ctor=gen_func,
                        maze_ctor_kwargs=dict(),
                        endpoint_kwargs=ep_kw,
                    )
                    for grid_n in grid_sizes
                ]
            )

    # get results
    result: SweepResult = SweepResult.analyze(
        configs=configs,
        param_values=np.linspace(0.0, 1.0, p_val_count).tolist(),
        param_key="maze_ctor_kwargs.p",
        analyze_func=dataset_success_fraction,
        parallel=False,
    )

    # save the result
    result.save(save_dir / f"result-n{n_mazes}-c{len(configs)}.zanj")

    return result


def plot_grouped(
    results: SweepResult,
    save_dir: Path | None = None,
    show: bool = True,
) -> None:
    """Plot grouped sweep results -- plot for each distinct `endpoint_kwargs` in the configs, with separate colormaps for each maze generator function

    # Parameters:
     - `results : SweepResult`
        The sweep results to plot
     - `save_dir : Path | None`
        Directory to save plots (defaults to `None`, meaning no saving)
     - `show : bool`
        Whether to display the plots (defaults to `True`)

    # Usage:
    ```python
    >>> result = full_analysis(n_mazes=100, p_val_count=11, grid_sizes=[8,16])
    >>> plot_grouped(result, save_dir=Path("./plots"), show=False)
    ```
    """


    # groups
    endpoint_kwargs_set: set[tuple[dict]] = results.configs_value_set("endpoint_kwargs")
    generator_funcs_names: list[str] = list({
        cfg.maze_ctor.__name__ for cfg in results.configs
    })

    # separate plot for each set of endpoint kwargs
    for ep_kw in endpoint_kwargs_set:
        results_epkw: SweepResult = results.get_where("endpoint_kwargs", lambda x: x == ep_kw)
        shared_keys: set[str] = set(results_epkw.configs_shared().keys())
        cfg_keys: set[str] = shared_keys.intersection(
            {"n_mazes", "endpoint_kwargs"}
        )
        fig, ax = plt.subplots(1, 1, figsize=(22, 10))
        for gf_idx, gen_func in enumerate(generator_funcs_names):
            results_filtered: SweepResult = results_epkw.get_where("maze_ctor", lambda x: x.__name__ == gen_func)
            ax = results_filtered.plot(
                cfg_keys=cfg_keys,
                ax=ax,
                show=False,
                cmap_name="Reds" if gf_idx == 0 else "Blues",
            )

        # save and show
        if save_dir:
            save_path: Path = save_dir / f"ep_{ep_kw}.svg"
            save_path.parent.mkdir(exist_ok=True, parents=True)
            plt.savefig(save_path)
        
        if show:
            plt.show()






















# # Group configs by endpoint_kwargs
# # We'll convert the endpoint_kwargs dict into a sorted tuple of (k,v) so it's hashable as a key
# grouped_by_ep: dict[tuple[tuple[str, Any], ...], list[MazeDatasetConfig]] = {}
# for cfg in results.configs:
#     ep_key: tuple[tuple[str, Any], ...] = tuple(sorted(cfg.endpoint_kwargs.items()))
#     if ep_key not in grouped_by_ep:
#         grouped_by_ep[ep_key] = []
#     grouped_by_ep[ep_key].append(cfg)

# # For each endpoint_kwargs group, we plot lines grouped by generator function
# for ep_key, cfg_list in grouped_by_ep.items():
#     # Build second-level grouping by generator function
#     group_by_gen: dict[str, list[MazeDatasetConfig]] = {}
#     for c in cfg_list:
#         gen_name: str = c.maze_ctor.__name__
#         if gen_name not in group_by_gen:
#             group_by_gen[gen_name] = []
#         group_by_gen[gen_name].append(c)

#     fig: plt.Figure
#     ax: plt.Axes
#     fig, ax = plt.subplots(figsize=(10, 6))

#     # Prepare color mapping
#     cmap = plt.get_cmap("viridis")
#     n_generators: int = len(group_by_gen)
#     param_values: list[float] = results.param_values
#     n_mazes: int = cfg_list[0].n_mazes if cfg_list else 0  # for saving filename
#     p_val_count: int = len(param_values)

#     for i, (gen_name, sub_configs) in enumerate(sorted(group_by_gen.items())):
#         color = cmap(i / max(n_generators - 1, 1)) if n_generators > 1 else "blue"
#         # Plot each config with the same generator but different grid_n
#         for c in sorted(sub_configs, key=lambda cc: cc.grid_n):
#             result_array: Float[np.ndarray, "n_pvals"] = results.result_values[c.to_fname()]
#             line_label: str = f"{gen_name.removeprefix('gen_')}-{c.grid_n}"
#             ax.plot(
#                 param_values,
#                 result_array,
#                 ".-",
#                 color=color,
#                 label=line_label,
#             )

#     # Build a nice label or string for ep_key
#     # ep_key is a tuple of (key, value). We'll do a short text representation
#     ep_str: str = ", ".join(f"{k}={v}" for k, v in ep_key)

#     ax.set_title(f"Endpoint kwargs: {ep_str}")
#     ax.set_xlabel(results.param_key)
#     ax.set_ylabel(results.analyze_func.__name__)
#     ax.grid(True)
#     ax.legend(loc="best")

#     # Save if requested
#     if save_dir is not None:
#         ep_kw_name: str = "_".join(
#             f"{k}-{v}".replace(" ", "") for k, v in ep_key
#         )
#         save_path: Path = save_dir / f"n_{n_mazes}-pvc_{p_val_count}-ep_{ep_kw_name}.svg"
#         save_path.parent.mkdir(exist_ok=True, parents=True)
#         plt.savefig(save_path)

#     if show:
#         plt.show()
#     else:
#         plt.close(fig)



# # plots
# for ep_kw_name, ep_kw in ep_kwargs:
#     fig, ax = plt.subplots(1, 1, figsize=(22, 10))
#     for gf_idx, gen_func in enumerate(generators):
#         ax = result.plot(
#             # cfg_keys=["n_mazes", "endpoint_kwargs"],
#             ax=ax,
#             show=False,
#             cmap_name="Reds" if gf_idx == 0 else "Blues",
#         )

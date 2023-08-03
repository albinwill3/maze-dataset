"""TokenizationMode enum and the MazeTokenizer class"""
from enum import Enum
from functools import cached_property
from typing import Callable, Iterable, Mapping

import numpy as np
from muutils.json_serialize import (
    SerializableDataclass,
    serializable_dataclass,
    serializable_field,
)
from muutils.kappa import Kappa

from maze_dataset.constants import SPECIAL_TOKENS, CoordTup
from maze_dataset.tokenization.token_utils import (  # coord_to_indexed_string,; coord_to_str,
    _coord_to_strings_indexed,
    _coord_to_strings_UT,
    coords_to_strings,
    strings_to_coords,
)
from maze_dataset.utils import WhenMissing, corner_first_ndindex


class TokenizationMode(Enum):
    """mode of tokenization

    # Abbreviations:
    - `AOTP`: Ajacency list, Origin, Target, Path
    - `UT`: Unique Token (for each coordiate)
    - `CTT`: Coordinate Tuple Tokens (each coordinate is tokenized as a tuple of integers)

    # Modes:
    - `AOTP_UT_rasterized`: the "classic" mode: assigning tokens to each coordinate is done via rasterization
        example: for a 3x3 maze, token order is `(0,0), (0,1), (0,2), (1,0), (1,1), (1,2), (2,0), (2,1), (2,2)`
    - `AOTP_UT_uniform`: new mode, where a 3x3 tokenization scheme and 5x5 tokenizations scheme are compatible
        uses `corner_first_ndindex` function to order the tokens
    - `AOTP_indexed`: each coordinate is a tuple of integers (not implemented)
    """

    AOTP_UT_rasterized = "AOTP_UT_rasterized"
    AOTP_UT_uniform = "AOTP_UT_uniform"
    AOTP_indexed = "AOTP_indexed"


_NDINDEX_FUNC_MAP: dict[
    TokenizationMode, Callable[[int], Iterable[tuple[int, ...]]]
] = {
    TokenizationMode.AOTP_UT_rasterized: np.ndindex,
    TokenizationMode.AOTP_UT_uniform: corner_first_ndindex,
}

_MAZETOKENIZER_PROPERTIES_TO_SERIALIZE: list[str] = [
    "name",
    "grid_size",
    "padding_token_index",
    "token_arr",
    "tokenizer_map",
    "token_node_map",
    "vocab_size",
]


@serializable_dataclass(properties_to_serialize=_MAZETOKENIZER_PROPERTIES_TO_SERIALIZE, kw_only=True)
class MazeTokenizer(SerializableDataclass):
    """Tokenizer for mazes 

    # Parameters:
     - `tokenization_mode: TokenizationMode`
        mode of tokenization. required.
    - `max_grid_size: int | None`
        maximum grid size. required for actually turning text tokens to numerical tokens, but not for moving between coordinates/mazes and text

    # Properties:
     - `name: str`
        auto-generated name of the tokenizer from mode and size
    - 
    """

    tokenization_mode: TokenizationMode = serializable_field(
        default=TokenizationMode.AOTP_UT_uniform,
        serialization_fn=lambda x: x.value,
        loading_fn=lambda x: TokenizationMode[x["tokenization_mode"]],
    )

    max_grid_size: int | None = serializable_field(default=None)

    @property
    def name(self) -> str:
        max_grid_size_str: str = (
            f"-g{self.max_grid_size}" if self.max_grid_size is not None else ""
        )
        return f"maze_tokenizer-{self.tokenization_mode.value}{max_grid_size_str}"

    @cached_property
    def node_token_map(self) -> Mapping[CoordTup, str]:
        """map from node to token"""
        if self.max_grid_size is None:
            raise ValueError(
                "max_grid_size must be specified to use node_token_map property"
            )

        if self.tokenization_mode in (
            TokenizationMode.AOTP_UT_rasterized,
            TokenizationMode.AOTP_UT_uniform,
        ):
            return Kappa(
                lambda coord: _coord_to_strings_UT(tuple(coord))[0],
            )
        elif self.tokenization_mode == TokenizationMode.AOTP_indexed:
            raise NotImplementedError(
                "AOTP_indexed mode not compatible with node_token_map"
            )
        else:
            raise ValueError(
                f"Invalid tokenization mode {self.tokenization_mode}",
                f"expected one of {TokenizationMode.__members__}",
            )
    
    @cached_property
    def node_strings_map(self) -> Mapping[CoordTup, str]:
        """map a coordinate to a token"""
        if self.tokenization_mode in (
            TokenizationMode.AOTP_UT_rasterized,
            TokenizationMode.AOTP_UT_uniform,
        ):
            return Kappa(
                lambda coord: _coord_to_strings_UT(tuple(coord)),
            )
        elif self.tokenization_mode == TokenizationMode.AOTP_indexed:
            return _coord_to_strings_indexed(coord)

    @cached_property
    def token_node_map(self) -> dict[str, CoordTup]:
        """map from token to node"""
        raise DeprecationWarning("this isn't used anywhere??")
        return {v: k for k, v in self.node_token_map.items()}

    @cached_property
    def _token_arr(self) -> list[str]:
        """map from index to token"""
        if self.max_grid_size is None:
            raise ValueError(
                "max_grid_size must be specified to use node_token_map property"
            )

        output: list[str] = list(SPECIAL_TOKENS.values())

        if self.tokenization_mode in (
            TokenizationMode.AOTP_UT_rasterized,
            TokenizationMode.AOTP_UT_uniform,
        ):
            output.extend(self.node_token_map.values())
        elif self.tokenization_mode == TokenizationMode.AOTP_indexed:
            # TODO: this is hacky, but we don't want to modify the original SPECIAL_TOKENS since that will break old models
            output.extend(
                [
                    "(",
                    ",",
                    ")",  # new special chars
                    *map(str, range(self.max_grid_size)),  # numbers
                ]
            )
        else:
            raise ValueError(
                f"Invalid tokenization mode {self.tokenization_mode}",
                f"expected one of {TokenizationMode.__members__}",
            )
    
    @cached_property
    def token_arr(self) -> list[str]|None:
        if self.max_grid_size is None:
            return None
        return self._token_arr
    
    @cached_property
    def _tokenizer_map(self) -> dict[str, int]:
        """map from token to index"""
        return {token: i for i, token in enumerate(self.token_arr)}
    
    @cached_property
    def tokenizer_map(self) -> dict[str, int]|None:
        if self.max_grid_size is None:
            return None
        return self._tokenizer_map

    @property
    def _vocab_size(self) -> int:
        return len(self.token_arr)

    @property
    def vocab_size(self) -> int|None:
        if self.max_grid_size is None:
            return None
        return self._vocab_size

    @property
    def _n_tokens(self) -> int:
        # TODO: deprecate
        return self.vocab_size

    @property
    def n_tokens(self) -> int|None:
        if self.max_grid_size is None:
            return None
        return self._n_tokens

    @cached_property
    def _padding_token_index(self) -> int:
        return self.tokenizer_map[SPECIAL_TOKENS.PADDING]

    def coords_to_strings(
        self,
        coords: list[CoordTup],
        when_noncoord: WhenMissing = "skip",
    ) -> list[str]:
        if self.tokenization_mode in (
            TokenizationMode.AOTP_UT_rasterized,
            TokenizationMode.AOTP_UT_uniform,
        ):
            return coords_to_strings(
                coords=coords,
                coord_to_strings_func=_coord_to_strings_UT,
                when_noncoord=when_noncoord,
            )
        elif self.tokenization_mode == TokenizationMode.AOTP_indexed:
            return coords_to_strings(
                coords=coords,
                coord_to_strings_func=_coord_to_strings_indexed,
                when_noncoord=when_noncoord,
            )
        else:
            raise ValueError(
                f"Invalid tokenization mode {self.tokenization_mode}",
                f"expected one of {TokenizationMode.__members__}",
            )

    @staticmethod
    def strings_to_coords(
        text: str,
        when_noncoord: WhenMissing = "skip",
    ) -> list[str | CoordTup]:
        return strings_to_coords(text=text, when_noncoord=when_noncoord)

    def is_AOTP(self) -> bool:
        """returns true if a tokenization mode is Adjacency list, Origin, Target, Path"""
        return self.tokenization_mode in (
            TokenizationMode.AOTP_UT_rasterized,
            TokenizationMode.AOTP_UT_uniform,
            TokenizationMode.AOTP_indexed,
        )

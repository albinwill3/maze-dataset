import abc
import itertools
from dataclasses import dataclass
from typing import Callable, Iterable, Literal

import frozendict
import numpy as np
import pytest
from jaxtyping import Int
from pytest import mark, param
from muutils.misc import (
    flatten,
    dataclass_set_equals,
    get_all_subclasses,
    isinstance_by_type_name,
    IsDataclass,
)

from maze_dataset import LatticeMaze
from maze_dataset.constants import VOCAB, Connection, ConnectionArray
from maze_dataset.dataset.maze_dataset import MazeDatasetConfig
from maze_dataset.generation import numpy_rng
from maze_dataset.testing_utils import GRID_N, MAZE_DATASET
from maze_dataset.token_utils import (
    _coord_to_strings_UT,
    coords_to_strings,
    equal_except_adj_list_sequence,
    get_adj_list_tokens,
    get_origin_tokens,
    get_path_tokens,
    get_relative_direction,
    get_target_tokens,
    strings_to_coords,
    tokens_between,
)
from maze_dataset.tokenization import (
    MazeTokenizer,
    MazeTokenizerModular,
    PathTokenizers,
    StepTokenizers,
    TokenizationMode,
    get_tokens_up_to_path_start,
)
from maze_dataset.token_utils import (
    is_connection,
)
from maze_dataset.utils import (
    FiniteValued,
    all_instances,
    lattice_connection_array,
    manhattan_distance,
)

MAZE_TOKENS: tuple[list[str], str] = (
    "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
    "AOTP_UT",
)
MAZE_TOKENS_AOTP_CTT_indexed: tuple[list[str], str] = (
    "<ADJLIST_START> ( 0 , 1 ) <--> ( 1 , 1 ) ; ( 1 , 0 ) <--> ( 1 , 1 ) ; ( 0 , 1 ) <--> ( 0 , 0 ) ; <ADJLIST_END> <ORIGIN_START> ( 1 , 0 ) <ORIGIN_END> <TARGET_START> ( 1 , 1 ) <TARGET_END> <PATH_START> ( 1 , 0 ) ( 1 , 1 ) <PATH_END>".split(),
    "AOTP_CTT_indexed",
)
TEST_TOKEN_LISTS: list[tuple[list[str], str]] = [
    MAZE_TOKENS,
    MAZE_TOKENS_AOTP_CTT_indexed,
]


@mark.parametrize(
    "toks, tokenizer_name",
    [
        param(
            token_list[0],
            token_list[1],
            id=f"{token_list[1]}",
        )
        for token_list in TEST_TOKEN_LISTS
    ],
)
def test_tokens_between(toks: list[str], tokenizer_name: str):
    result = tokens_between(toks, "<PATH_START>", "<PATH_END>")
    match tokenizer_name:
        case "AOTP_UT":
            assert result == ["(1,0)", "(1,1)"]
        case "AOTP_CTT_indexed":
            assert result == ["(", "1", ",", "0", ")", "(", "1", ",", "1", ")"]

    # Normal case
    tokens = ["the", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog"]
    start_value = "quick"
    end_value = "over"
    assert tokens_between(tokens, start_value, end_value) == ["brown", "fox", "jumps"]

    # Including start and end values
    assert tokens_between(tokens, start_value, end_value, True, True) == [
        "quick",
        "brown",
        "fox",
        "jumps",
        "over",
    ]

    # When start_value or end_value is not unique and except_when_tokens_not_unique is True
    with pytest.raises(ValueError):
        tokens_between(tokens, "the", "dog", False, False, True)

    # When start_value or end_value is not unique and except_when_tokens_not_unique is False
    assert tokens_between(tokens, "the", "dog", False, False, False) == [
        "quick",
        "brown",
        "fox",
        "jumps",
        "over",
        "the",
        "lazy",
    ]

    # Empty tokens list
    with pytest.raises(ValueError):
        tokens_between([], "start", "end")

    # start_value and end_value are the same
    with pytest.raises(ValueError):
        tokens_between(tokens, "fox", "fox")

    # start_value or end_value not in the tokens list
    with pytest.raises(ValueError):
        tokens_between(tokens, "start", "end")

    # start_value comes after end_value in the tokens list
    with pytest.raises(AssertionError):
        tokens_between(tokens, "over", "quick")

    # start_value and end_value are at the beginning and end of the tokens list, respectively
    assert tokens_between(tokens, "the", "dog", True, True) == tokens

    # Single element in the tokens list, which is the same as start_value and end_value
    with pytest.raises(ValueError):
        tokens_between(["fox"], "fox", "fox", True, True)


@mark.parametrize(
    "toks, tokenizer_name",
    [
        param(
            token_list[0],
            token_list[1],
            id=f"{token_list[1]}",
        )
        for token_list in TEST_TOKEN_LISTS
    ],
)
def test_tokens_between_out_of_order(toks: list[str], tokenizer_name: str):
    with pytest.raises(AssertionError):
        tokens_between(toks, "<PATH_END>", "<PATH_START>")


@mark.parametrize(
    "toks, tokenizer_name",
    [
        param(
            token_list[0],
            token_list[1],
            id=f"{token_list[1]}",
        )
        for token_list in TEST_TOKEN_LISTS
    ],
)
def test_get_adj_list_tokens(toks: list[str], tokenizer_name: str):
    result = get_adj_list_tokens(toks)
    match tokenizer_name:
        case "AOTP_UT":
            expected = (
                "(0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ;".split()
            )
        case "AOTP_CTT_indexed":
            expected = "( 0 , 1 ) <--> ( 1 , 1 ) ; ( 1 , 0 ) <--> ( 1 , 1 ) ; ( 0 , 1 ) <--> ( 0 , 0 ) ;".split()
    assert result == expected


@mark.parametrize(
    "toks, tokenizer_name",
    [
        param(
            token_list[0],
            token_list[1],
            id=f"{token_list[1]}",
        )
        for token_list in TEST_TOKEN_LISTS
    ],
)
def test_get_path_tokens(toks: list[str], tokenizer_name: str):
    result_notrim = get_path_tokens(toks)
    result_trim = get_path_tokens(toks, trim_end=True)
    match tokenizer_name:
        case "AOTP_UT":
            assert result_notrim == ["<PATH_START>", "(1,0)", "(1,1)", "<PATH_END>"]
            assert result_trim == ["(1,0)", "(1,1)"]
        case "AOTP_CTT_indexed":
            assert (
                result_notrim == "<PATH_START> ( 1 , 0 ) ( 1 , 1 ) <PATH_END>".split()
            )
            assert result_trim == "( 1 , 0 ) ( 1 , 1 )".split()


@mark.parametrize(
    "toks, tokenizer_name",
    [
        param(
            token_list[0],
            token_list[1],
            id=f"{token_list[1]}",
        )
        for token_list in TEST_TOKEN_LISTS
    ],
)
def test_get_origin_tokens(toks: list[str], tokenizer_name: str):
    result = get_origin_tokens(toks)
    match tokenizer_name:
        case "AOTP_UT":
            assert result == ["(1,0)"]
        case "AOTP_CTT_indexed":
            assert result == "( 1 , 0 )".split()


@mark.parametrize(
    "toks, tokenizer_name",
    [
        param(
            token_list[0],
            token_list[1],
            id=f"{token_list[1]}",
        )
        for token_list in TEST_TOKEN_LISTS
    ],
)
def test_get_target_tokens(toks: list[str], tokenizer_name: str):
    result = get_target_tokens(toks)
    match tokenizer_name:
        case "AOTP_UT":
            assert result == ["(1,1)"]
        case "AOTP_CTT_indexed":
            assert result == "( 1 , 1 )".split()


@mark.parametrize(
    "toks, tokenizer_name",
    [
        param(
            token_list[0],
            token_list[1],
            id=f"{token_list[1]}",
        )
        for token_list in [MAZE_TOKENS]
    ],
)
def test_get_tokens_up_to_path_start_including_start(
    toks: list[str], tokenizer_name: str
):
    # Dont test on `MAZE_TOKENS_AOTP_CTT_indexed` because this function doesn't support `AOTP_CTT_indexed` when `include_start_coord=True`.
    result = get_tokens_up_to_path_start(toks, include_start_coord=True)
    match tokenizer_name:
        case "AOTP_UT":
            expected = "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0)".split()
        case "AOTP_CTT_indexed":
            expected = "<ADJLIST_START> ( 0 , 1 ) <--> ( 1 , 1 ) ; ( 1 , 0 ) <--> ( 1 , 1 ) ; ( 0 , 1 ) <--> ( 0 , 0 ) ; <ADJLIST_END> <ORIGIN_START> ( 1 , 0 ) <ORIGIN_END> <TARGET_START> ( 1 , 1 ) <TARGET_END> <PATH_START> ( 1 , 0 )".split()
    assert result == expected


@mark.parametrize(
    "toks, tokenizer_name",
    [
        param(
            token_list[0],
            token_list[1],
            id=f"{token_list[1]}",
        )
        for token_list in TEST_TOKEN_LISTS
    ],
)
def test_get_tokens_up_to_path_start_excluding_start(
    toks: list[str], tokenizer_name: str
):
    result = get_tokens_up_to_path_start(toks, include_start_coord=False)
    match tokenizer_name:
        case "AOTP_UT":
            expected = "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START>".split()
        case "AOTP_CTT_indexed":
            expected = "<ADJLIST_START> ( 0 , 1 ) <--> ( 1 , 1 ) ; ( 1 , 0 ) <--> ( 1 , 1 ) ; ( 0 , 1 ) <--> ( 0 , 0 ) ; <ADJLIST_END> <ORIGIN_START> ( 1 , 0 ) <ORIGIN_END> <TARGET_START> ( 1 , 1 ) <TARGET_END> <PATH_START>".split()
    assert result == expected


@mark.parametrize(
    "toks, tokenizer_name",
    [
        param(
            token_list[0],
            token_list[1],
            id=f"{token_list[1]}",
        )
        for token_list in TEST_TOKEN_LISTS
    ],
)
def test_strings_to_coords(toks: list[str], tokenizer_name: str):
    adj_list = get_adj_list_tokens(toks)
    skipped = strings_to_coords(adj_list, when_noncoord="skip")
    included = strings_to_coords(adj_list, when_noncoord="include")

    assert skipped == [
        (0, 1),
        (1, 1),
        (1, 0),
        (1, 1),
        (0, 1),
        (0, 0),
    ]

    assert included == [
        (0, 1),
        "<-->",
        (1, 1),
        ";",
        (1, 0),
        "<-->",
        (1, 1),
        ";",
        (0, 1),
        "<-->",
        (0, 0),
        ";",
    ]

    with pytest.raises(ValueError):
        strings_to_coords(adj_list, when_noncoord="error")

    assert strings_to_coords("(1,2) <ADJLIST_START> (5,6)") == [(1, 2), (5, 6)]
    assert strings_to_coords("(1,2) <ADJLIST_START> (5,6)", when_noncoord="skip") == [
        (1, 2),
        (5, 6),
    ]
    assert strings_to_coords(
        "(1,2) <ADJLIST_START> (5,6)", when_noncoord="include"
    ) == [(1, 2), "<ADJLIST_START>", (5, 6)]
    with pytest.raises(ValueError):
        strings_to_coords("(1,2) <ADJLIST_START> (5,6)", when_noncoord="error")


@mark.parametrize(
    "toks, tokenizer_name",
    [
        param(
            token_list[0],
            token_list[1],
            id=f"{token_list[1]}",
        )
        for token_list in TEST_TOKEN_LISTS
    ],
)
def test_coords_to_strings(toks: list[str], tokenizer_name: str):
    adj_list = get_adj_list_tokens(toks)
    config = MazeDatasetConfig(name="test", grid_n=2, n_mazes=1)
    coords = strings_to_coords(adj_list, when_noncoord="include")

    skipped = coords_to_strings(
        coords, coord_to_strings_func=_coord_to_strings_UT, when_noncoord="skip"
    )
    included = coords_to_strings(
        coords, coord_to_strings_func=_coord_to_strings_UT, when_noncoord="include"
    )

    assert skipped == [
        "(0,1)",
        "(1,1)",
        "(1,0)",
        "(1,1)",
        "(0,1)",
        "(0,0)",
    ]

    assert included == [
        "(0,1)",
        "<-->",
        "(1,1)",
        ";",
        "(1,0)",
        "<-->",
        "(1,1)",
        ";",
        "(0,1)",
        "<-->",
        "(0,0)",
        ";",
    ]

    with pytest.raises(ValueError):
        coords_to_strings(
            coords, coord_to_strings_func=_coord_to_strings_UT, when_noncoord="error"
        )


def test_equal_except_adj_list_sequence():
    assert equal_except_adj_list_sequence(MAZE_TOKENS[0], MAZE_TOKENS[0])
    assert not equal_except_adj_list_sequence(
        MAZE_TOKENS[0], MAZE_TOKENS_AOTP_CTT_indexed[0]
    )
    assert equal_except_adj_list_sequence(
        "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
        "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
    )
    assert equal_except_adj_list_sequence(
        "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
        "<ADJLIST_START> (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; (0,1) <--> (1,1) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
    )
    assert equal_except_adj_list_sequence(
        "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
        "<ADJLIST_START> (1,1) <--> (0,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
    )
    assert not equal_except_adj_list_sequence(
        "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
        "<ADJLIST_START> (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; (0,1) <--> (1,1) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,1) (1,0) <PATH_END>".split(),
    )
    assert not equal_except_adj_list_sequence(
        "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
        "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END> <PATH_END>".split(),
    )
    assert not equal_except_adj_list_sequence(
        "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
        "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
    )
    assert not equal_except_adj_list_sequence(
        "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
        "(0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
    )
    with pytest.raises(ValueError):
        equal_except_adj_list_sequence(
            "(0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
            "(0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
        )
    with pytest.raises(ValueError):
        equal_except_adj_list_sequence(
            "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
            "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
        )
    assert not equal_except_adj_list_sequence(
        "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ADJLIST_END> <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
        "<ADJLIST_START> (0,1) <--> (1,1) ; (1,0) <--> (1,1) ; (0,1) <--> (0,0) ; <ORIGIN_START> (1,0) <ORIGIN_END> <TARGET_START> (1,1) <TARGET_END> <PATH_START> (1,0) (1,1) <PATH_END>".split(),
    )

    # CTT
    assert equal_except_adj_list_sequence(
        "<ADJLIST_START> ( 0 , 1 ) <--> ( 1 , 1 ) ; ( 1 , 0 ) <--> ( 1 , 1 ) ; ( 0 , 1 ) <--> ( 0 , 0 ) ; <ADJLIST_END> <ORIGIN_START> ( 1 , 0 ) <ORIGIN_END> <TARGET_START> ( 1 , 1 ) <TARGET_END> <PATH_START> ( 1 , 0 ) ( 1 , 1 ) <PATH_END>".split(),
        "<ADJLIST_START> ( 0 , 1 ) <--> ( 1 , 1 ) ; ( 1 , 0 ) <--> ( 1 , 1 ) ; ( 0 , 1 ) <--> ( 0 , 0 ) ; <ADJLIST_END> <ORIGIN_START> ( 1 , 0 ) <ORIGIN_END> <TARGET_START> ( 1 , 1 ) <TARGET_END> <PATH_START> ( 1 , 0 ) ( 1 , 1 ) <PATH_END>".split(),
    )
    assert equal_except_adj_list_sequence(
        "<ADJLIST_START> ( 0 , 1 ) <--> ( 1 , 1 ) ; ( 1 , 0 ) <--> ( 1 , 1 ) ; ( 0 , 1 ) <--> ( 0 , 0 ) ; <ADJLIST_END> <ORIGIN_START> ( 1 , 0 ) <ORIGIN_END> <TARGET_START> ( 1 , 1 ) <TARGET_END> <PATH_START> ( 1 , 0 ) ( 1 , 1 ) <PATH_END>".split(),
        "<ADJLIST_START> ( 1 , 1 ) <--> ( 0 , 1 ) ; ( 1 , 0 ) <--> ( 1 , 1 ) ; ( 0 , 1 ) <--> ( 0 , 0 ) ; <ADJLIST_END> <ORIGIN_START> ( 1 , 0 ) <ORIGIN_END> <TARGET_START> ( 1 , 1 ) <TARGET_END> <PATH_START> ( 1 , 0 ) ( 1 , 1 ) <PATH_END>".split(),
    )
    # This inactive test demonstrates the lack of robustness of the function for comparing source `LatticeMaze` objects.
    # See function documentation for details.
    # assert not equal_except_adj_list_sequence(
    #     "<ADJLIST_START> ( 0 , 1 ) <--> ( 1 , 1 ) ; ( 1 , 0 ) <--> ( 1 , 1 ) ; ( 0 , 1 ) <--> ( 0 , 0 ) ; <ADJLIST_END> <ORIGIN_START> ( 1 , 0 ) <ORIGIN_END> <TARGET_START> ( 1 , 1 ) <TARGET_END> <PATH_START> ( 1 , 0 ) ( 1 , 1 ) <PATH_END>".split(),
    #     "<ADJLIST_START> ( 1 , 0 ) <--> ( 1 , 1 ) ; ( 1 , 0 ) <--> ( 1 , 1 ) ; ( 0 , 1 ) <--> ( 0 , 0 ) ; <ADJLIST_END> <ORIGIN_START> ( 1 , 0 ) <ORIGIN_END> <TARGET_START> ( 1 , 1 ) <TARGET_END> <PATH_START> ( 1 , 0 ) ( 1 , 1 ) <PATH_END>".split()
    # )


@mark.parametrize(
    "deep, flat, depth",
    [
        param(
            iter_tuple[0],
            iter_tuple[1],
            iter_tuple[2],
            id=f"{i}",
        )
        for i, iter_tuple in enumerate(
            [
                ([1, 2, 3, 4], [1, 2, 3, 4], None),
                ((1, 2, 3, 4), [1, 2, 3, 4], None),
                ((j for j in [1, 2, 3, 4]), [1, 2, 3, 4], None),
                (["a", "b", "c", "d"], ["a", "b", "c", "d"], None),
                ("funky duck", [c for c in "funky duck"], None),
                (["funky", "duck"], ["funky", "duck"], None),
                (b"funky duck", [b for b in b"funky duck"], None),
                ([b"funky", b"duck"], [b"funky", b"duck"], None),
                ([[1, 2, 3, 4]], [1, 2, 3, 4], None),
                ([[[[1, 2, 3, 4]]]], [1, 2, 3, 4], None),
                ([[[[1], 2], 3], 4], [1, 2, 3, 4], None),
                ([[1, 2], [[3]], (4,)], [1, 2, 3, 4], None),
                ([[[1, 2, 3, 4]]], [[1, 2, 3, 4]], 1),
                ([[[1, 2, 3, 4]]], [1, 2, 3, 4], 2),
                ([[1, 2], [[3]], (4,)], [1, 2, [3], 4], 1),
                ([[1, 2], [(3,)], (4,)], [1, 2, (3,), 4], 1),
                ([[[[1], 2], 3], 4], [[1], 2, 3, 4], 2),
            ]
        )
    ],
)
def test_flatten(deep: Iterable[any], flat: Iterable[any], depth: int | None):
    assert list(flatten(deep, depth)) == flat


def test_get_all_subclasses():
    class A:
        pass

    class B(A):
        pass

    class C(A):
        pass

    class D(B, C):
        pass

    class E(B):
        pass

    class F(D):
        pass

    class Z:
        pass

    assert get_all_subclasses(A) == {B, C, D, E, F}
    assert get_all_subclasses(A, include_self=True) == {A, B, C, D, E, F}
    assert get_all_subclasses(B) == {D, E, F}
    assert get_all_subclasses(C) == {D, F}
    assert get_all_subclasses(D) == {F}
    assert get_all_subclasses(D, include_self=True) == {D, F}
    assert get_all_subclasses(Z) == set()
    assert get_all_subclasses(Z, include_self=True) == {Z}


# Test classes
@dataclass
class DC1:
    x: bool
    y: bool = False


@dataclass(frozen=True)
class DC2:
    x: bool
    y: bool = False


@dataclass(frozen=True)
class DC3:
    x: DC2 = DC2(False, False)


@dataclass(frozen=True)
class DC4:
    x: DC2
    y: bool = False


@dataclass(frozen=True)
class DC5:
    x: int


@dataclass(frozen=True)
class DC6:
    x: DC5
    y: bool = False


@dataclass(frozen=True)
class DC7(abc.ABC):
    x: bool

    @abc.abstractmethod
    def foo():
        pass


@dataclass(frozen=True)
class DC8(DC7):
    x: bool = False

    def foo():
        pass


@dataclass(frozen=True)
class DC9(DC7):
    y: bool = True

    def foo():
        pass


# TODO: this can definitely be generated programmatically
@mark.parametrize(
    "type_, validation_funcs, result",
    [
        param(
            type_,
            vfs,
            result,
            id=f"{type_}-vfs[{len(vfs) if vfs is not None else 'None'}]",
        )
        for type_, vfs, result in (
            [
                (
                    DC1,
                    None,
                    [
                        DC1(False, False),
                        DC1(False, True),
                        DC1(True, False),
                        DC1(True, True),
                    ],
                ),
                (
                    DC2,
                    None,
                    [
                        DC2(False, False),
                        DC2(False, True),
                        DC2(True, False),
                        DC2(True, True),
                    ],
                ),
                (
                    DC2,
                    {DC2: lambda dc: dc.x ^ dc.y},
                    [
                        DC2(False, True),
                        DC2(True, False),
                    ],
                ),
                (
                    DC1 | DC2,
                    {DC2: lambda dc: dc.x ^ dc.y},
                    [
                        DC2(False, True),
                        DC2(True, False),
                        DC1(False, False),
                        DC1(False, True),
                        DC1(True, False),
                        DC1(True, True),
                    ],
                ),
                (
                    DC1 | DC2,
                    {
                        DC1: lambda dc: dc.x == dc.y,
                        DC2: lambda dc: dc.x ^ dc.y,
                    },
                    [
                        DC2(False, True),
                        DC2(True, False),
                        DC1(False, False),
                        DC1(True, True),
                    ],
                ),
                (
                    DC3,
                    None,
                    [
                        DC3(DC2(False, False)),
                        DC3(DC2(False, True)),
                        DC3(DC2(True, False)),
                        DC3(DC2(True, True)),
                    ],
                ),
                (
                    DC4,
                    None,
                    [
                        DC4(DC2(False, False), True),
                        DC4(DC2(False, True), True),
                        DC4(DC2(True, False), True),
                        DC4(DC2(True, True), True),
                        DC4(DC2(False, False), False),
                        DC4(DC2(False, True), False),
                        DC4(DC2(True, False), False),
                        DC4(DC2(True, True), False),
                    ],
                ),
                (
                    DC4,
                    {DC2: lambda dc: dc.x ^ dc.y},
                    [
                        DC4(DC2(False, True), True),
                        DC4(DC2(True, False), True),
                        DC4(DC2(False, True), False),
                        DC4(DC2(True, False), False),
                    ],
                ),
                (DC5, None, TypeError),
                (DC6, None, TypeError),
                (bool, None, [True, False]),
                (bool, {bool: lambda x: x}, [True]),
                (bool, {bool: lambda x: not x}, [False]),
                (int, None, TypeError),
                (str, None, TypeError),
                (Literal[0, 1, 2], None, [0, 1, 2]),
                (Literal[0, 1, 2], {int: lambda x: x % 2 == 0}, [0, 2]),
                (bool | Literal[0, 1, 2], dict(), [0, 1, 2, True, False]),
                (bool | Literal[0, 1, 2], {bool: lambda x: x}, [0, 1, 2, True]),
                (bool | Literal[0, 1, 2], {int: lambda x: x % 2}, [1, True]),
                (
                    tuple[bool],
                    None,
                    [
                        (True,),
                        (False,),
                    ],
                ),
                (
                    tuple[bool, bool],
                    None,
                    [
                        (True, True),
                        (True, False),
                        (False, True),
                        (False, False),
                    ],
                ),
                (
                    tuple[bool, bool],
                    {bool: lambda x: x},
                    [
                        (True, True),
                    ],
                ),
                (
                    DC8,
                    None,
                    [
                        DC8(False),
                        DC8(True),
                    ],
                ),
                (
                    DC7,
                    None,
                    [
                        DC8(False),
                        DC8(True),
                        DC9(False, False),
                        DC9(False, True),
                        DC9(True, False),
                        DC9(True, True),
                    ],
                ),
                (
                    tuple[DC7],
                    None,
                    [
                        (DC8(False),),
                        (DC8(True),),
                        (DC9(False, False),),
                        (DC9(False, True),),
                        (DC9(True, False),),
                        (DC9(True, True),),
                    ],
                ),
                (
                    tuple[DC7],
                    {DC9: lambda dc: dc.x == dc.y},
                    [
                        (DC8(False),),
                        (DC8(True),),
                        (DC9(False, False),),
                        (DC9(True, True),),
                    ],
                ),
                (
                    tuple[DC8, DC8],
                    None,
                    [
                        (DC8(False), DC8(False)),
                        (DC8(False), DC8(True)),
                        (DC8(True), DC8(False)),
                        (DC8(True), DC8(True)),
                    ],
                ),
                (
                    tuple[DC7, bool],
                    None,
                    [
                        (DC8(False), True),
                        (DC8(True), True),
                        (DC9(False, False), True),
                        (DC9(False, True), True),
                        (DC9(True, False), True),
                        (DC9(True, True), True),
                        (DC8(False), False),
                        (DC8(True), False),
                        (DC9(False, False), False),
                        (DC9(False, True), False),
                        (DC9(True, False), False),
                        (DC9(True, True), False),
                    ],
                ),
            ]
        )
    ],
)
def test_all_instances(
    type_: FiniteValued,
    validation_funcs: dict[FiniteValued, Callable[[FiniteValued], bool]] | None,
    result: type[Exception] | Iterable[FiniteValued],
):
    if isinstance(result, type) and issubclass(result, Exception):
        with pytest.raises(result):
            list(all_instances(type_, validation_funcs))
    elif hasattr(type_, "__dataclass_fields__"):
        assert dataclass_set_equals(all_instances(type_, validation_funcs), result)
    else:  # General case, due to nesting, results might contain some dataclasses and some other types
        out = list(all_instances(type_, validation_funcs))
        assert dataclass_set_equals(
            filter(lambda x: isinstance(x, IsDataclass), out),
            filter(lambda x: isinstance(x, IsDataclass), result),
        )
        assert set(filter(lambda x: not isinstance(x, IsDataclass), out)) == set(
            filter(lambda x: not isinstance(x, IsDataclass), result)
        )


# @mivanit: this was really difficult to understand
@mark.parametrize(
    "type_, validation_funcs, assertion",
    [
        param(
            type_,
            vfs,
            assertion,
            id=f"{i}-{type_.__name__}",
        )
        for i, (type_, vfs, assertion) in enumerate(
            [
                (
                    # type
                    PathTokenizers._PathTokenizer,
                    # validation_funcs
                    dict(),
                    # assertion
                    lambda x: PathTokenizers.StepSequence(
                        step_tokenizers=(StepTokenizers.Distance(),)
                    )
                    in x,
                ),
                (
                    # type
                    PathTokenizers._PathTokenizer,
                    # validation_funcs
                    {PathTokenizers._PathTokenizer: lambda x: x.is_valid()},
                    # assertion
                    lambda x: PathTokenizers.StepSequence(
                        step_tokenizers=(StepTokenizers.Distance(),)
                    )
                    not in x
                    and PathTokenizers.StepSequence(
                        step_tokenizers=(
                            StepTokenizers.Coord(),
                            StepTokenizers.Coord(),
                        )
                    )
                    not in x,
                ),
            ]
        )
    ],
)
def test_all_instances2(
    type_: FiniteValued,
    validation_funcs: frozendict.frozendict[
        FiniteValued, Callable[[FiniteValued], bool]
    ],
    assertion: Callable[[list[FiniteValued]], bool],
):
    assert assertion(all_instances(type_, validation_funcs))


@mark.parametrize(
    "coll1, coll2, result",
    [
        param(
            c1,
            c2,
            res,
            id=f"{c1}_{c2}",
        )
        for c1, c2, res in (
            [
                (
                    [
                        DC1(False, False),
                        DC1(False, True),
                    ],
                    [
                        DC1(True, False),
                        DC1(True, True),
                    ],
                    False,
                ),
                (
                    [
                        DC1(False, False),
                        DC1(False, True),
                    ],
                    [
                        DC1(False, False),
                        DC1(False, True),
                    ],
                    True,
                ),
                (
                    [
                        DC1(False, False),
                        DC1(False, True),
                    ],
                    [
                        DC2(False, False),
                        DC2(False, True),
                    ],
                    False,
                ),
                (
                    [
                        DC3(False),
                        DC3(False),
                    ],
                    [
                        DC3(False),
                    ],
                    True,
                ),
                ([], [], True),
                ([DC5], [DC5], AttributeError),
            ]
        )
    ],
)
def test_dataclass_set_equals(
    coll1: Iterable[IsDataclass],
    coll2: Iterable[IsDataclass],
    result: bool | type[Exception],
):
    if isinstance(result, type) and issubclass(result, Exception):
        with pytest.raises(result):
            dataclass_set_equals(coll1, coll2)
    else:
        assert dataclass_set_equals(coll1, coll2) == result


@mark.parametrize(
    "o, type_name, result",
    [
        param(
            o,
            name,
            res,
            id=f"{o}_{name}",
        )
        for o, name, res in (
            [
                (True, "bool", True),
                (True, "int", True),
                (1, "int", True),
                (1, "bool", False),
                (MazeTokenizer(), "MazeTokenizer", True),
                (MazeTokenizer(), "TokenizationMode", False),
                (MazeTokenizerModular(), "MazeTokenizerModular", True),
                (MazeTokenizerModular(), "MazeTokenizer", False),
                (TokenizationMode.AOTP_CTT_indexed, "TokenizationMode", True),
                (TokenizationMode.AOTP_UT_uniform, "MazeTokenizer", False),
                (StepTokenizers.Distance(), "_StepTokenizer", True),
                (StepTokenizers.Distance(), "_TokenizerElement", True),
                (PathTokenizers.StepSequence(), "StepSequence", True),
                (PathTokenizers.StepSequence(), "_PathTokenizer", True),
                (MazeTokenizerModular, "MazeTokenizerModular", False),
                (TokenizationMode, "TokenizationMode", False),
            ]
        )
    ],
)
def test_isinstance_by_type_name(
    o: object, type_name: str, result: bool | type[Exception]
):
    if isinstance(result, type) and issubclass(result, Exception):
        with pytest.raises(result):
            isinstance_by_type_name(o, type_name)
    else:
        assert isinstance_by_type_name(o, type_name) == result


@mark.parametrize(
    "coords, result",
    [
        param(
            np.array(coords),
            res,
            id=f"{coords}",
        )
        for coords, res in (
            [
                ([[0, 0], [0, 1], [1, 1]], VOCAB.PATH_RIGHT),
                ([[0, 0], [1, 0], [1, 1]], VOCAB.PATH_LEFT),
                ([[0, 0], [0, 1], [0, 2]], VOCAB.PATH_FORWARD),
                ([[0, 0], [0, 1], [0, 0]], VOCAB.PATH_BACKWARD),
                ([[0, 0], [0, 1], [0, 1]], VOCAB.PATH_STAY),
                ([[1, 1], [0, 1], [0, 0]], VOCAB.PATH_LEFT),
                ([[1, 1], [1, 0], [0, 0]], VOCAB.PATH_RIGHT),
                ([[0, 2], [0, 1], [0, 0]], VOCAB.PATH_FORWARD),
                ([[0, 0], [0, 1], [0, 0]], VOCAB.PATH_BACKWARD),
                ([[0, 1], [0, 1], [0, 0]], ValueError),
                ([[0, 1], [1, 1], [0, 0]], ValueError),
                ([[1, 0], [1, 1], [0, 0]], ValueError),
                ([[0, 1], [0, 2], [0, 0]], ValueError),
                ([[0, 1], [0, 0], [0, 0]], VOCAB.PATH_STAY),
                ([[1, 1], [0, 0], [0, 1]], ValueError),
                ([[1, 1], [0, 0], [1, 0]], ValueError),
                ([[0, 2], [0, 0], [0, 1]], ValueError),
                ([[0, 0], [0, 0], [0, 1]], ValueError),
                ([[0, 1], [0, 0], [0, 1]], VOCAB.PATH_BACKWARD),
                ([[-1, 0], [0, 0], [1, 0]], VOCAB.PATH_FORWARD),
                ([[-1, 0], [0, 0], [0, 1]], VOCAB.PATH_LEFT),
                ([[-1, 0], [0, 0], [-1, 0]], VOCAB.PATH_BACKWARD),
                ([[-1, 0], [0, 0], [0, -1]], VOCAB.PATH_RIGHT),
                ([[-1, 0], [0, 0], [1, 0], [2, 0]], ValueError),
                ([[-1, 0], [0, 0]], ValueError),
                ([[-1, 0, 0], [0, 0, 0]], ValueError),
            ]
        )
    ],
)
def test_get_relative_direction(
    coords: Int[np.ndarray, "prev_cur_next=3 axis=2"], result: str | type[Exception]
):
    if isinstance(result, type) and issubclass(result, Exception):
        with pytest.raises(result):
            get_relative_direction(coords)
        return
    assert get_relative_direction(coords) == result


@mark.parametrize(
    "edges, result",
    [
        param(
            edges,
            res,
            id=f"{edges}",
        )
        for edges, res in (
            [
                (np.array([[0, 0], [0, 1]]), 1),
                (np.array([[1, 0], [0, 1]]), 2),
                (np.array([[-1, 0], [0, 1]]), 2),
                (np.array([[0, 0], [5, 3]]), 8),
                (
                    np.array(
                        [
                            [[0, 0], [0, 1]],
                            [[1, 0], [0, 1]],
                            [[-1, 0], [0, 1]],
                            [[0, 0], [5, 3]],
                        ]
                    ),
                    [1, 2, 2, 8],
                ),
                (np.array([[[0, 0], [5, 3]]]), [8]),
            ]
        )
    ],
)
def test_manhattan_distance(
    edges: ConnectionArray | Connection,
    result: Int[np.ndarray, "edges"] | Int[np.ndarray, ""] | type[Exception],
):
    if isinstance(result, type) and issubclass(result, Exception):
        with pytest.raises(result):
            manhattan_distance(edges)
        return
    assert np.array_equal(manhattan_distance(edges), np.array(result, dtype=np.int8))


@mark.parametrize(
    "n",
    [param(n) for n in [2, 3, 5, 20]],
)
def test_lattice_connection_arrray(n):
    edges = lattice_connection_array(n)
    assert tuple(edges.shape) == (2 * n * (n - 1), 2, 2)
    assert np.all(np.sum(edges[:, 1], axis=1) > np.sum(edges[:, 0], axis=1))
    assert tuple(np.unique(edges, axis=0).shape) == (2 * n * (n - 1), 2, 2)


@mark.parametrize(
    "edges, maze",
    [
        param(
            edges(),
            maze,
            id=f"edges[{i}]; maze[{j}]",
        )
        for (i, edges), (j, maze) in itertools.product(
            enumerate(
                [
                    lambda: lattice_connection_array(GRID_N),
                    lambda: np.flip(lattice_connection_array(GRID_N), axis=1),
                    lambda: lattice_connection_array(GRID_N - 1),
                    lambda: numpy_rng.choice(
                        lattice_connection_array(GRID_N), 2 * GRID_N, axis=0
                    ),
                    lambda: numpy_rng.choice(
                        lattice_connection_array(GRID_N), 1, axis=0
                    ),
                ]
            ),
            enumerate(MAZE_DATASET.mazes),
        )
    ],
)
def test_is_connection(edges: ConnectionArray, maze: LatticeMaze):
    output = is_connection(edges, maze.connection_list)
    sorted_edges = np.sort(edges, axis=1)
    edge_direction = (
        (sorted_edges[:, 1, :] - sorted_edges[:, 0, :])[:, 0] == 0
    ).astype(np.int8)
    assert np.array_equal(
        output,
        maze.connection_list[
            edge_direction, sorted_edges[:, 0, 0], sorted_edges[:, 0, 1]
        ],
    )

"""The catalog's embedding seam.

The bug this guards against has already happened: 77 assets hold 768-d Gemini
vectors in a field the matcher queries, and every search over them was noise
nobody noticed. A vector of the wrong width is not a weaker match -- it is a
meaningless one, so the seam raises rather than storing it.
"""
import pytest

from menu.pipeline import item_embed


def test_the_catalog_width_is_the_nvidia_models_width():
    assert item_embed.DIMENSIONS == 1024


def test_no_provider_means_no_vector_rather_than_an_error():
    """Spec D6: every AI layer is optional and the wizard must work with every
    endpoint dead. No embedder simply switches the vector layer off."""
    assert item_embed.PROVIDER is None
    assert item_embed.embed_text('black tea') is None


def test_an_injected_embedder_is_used():
    assert item_embed.embed_text('black tea',
                                 embedder=lambda t: [0.5] * 1024) == [0.5] * 1024


def test_a_vector_of_the_wrong_width_is_refused_not_stored():
    with pytest.raises(ValueError, match='768'):
        item_embed.embed_text('black tea', embedder=lambda t: [0.1] * 768)


def test_an_embedder_that_returns_nothing_is_not_an_error():
    assert item_embed.embed_text('black tea', embedder=lambda t: None) is None

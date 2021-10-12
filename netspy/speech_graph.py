# flake8: noqa
# pylint: skip-file

import pickle
import sys
import time
from pathlib import Path
from typing import Optional, Union

import matplotlib.pyplot as plt
import networkx as nx


from netspy import MultiDiGraph, preprocess
from netspy.config import get_settings
from netspy.clients import OpenIEClient, CoreNLPClient
from netspy.logger import logger
from netspy.nlp_helper_functions import (  # process_sent,; remove_bad_transcripts,; remove_duplicates,; remove_interjections,; remove_irrelevant_text,; replace_problematic_symbols,
    get_transcript_properties,
)
from netspy.visualise_paragraph_functions import (
    add_adj_edges,
    add_obl_edges,
    add_prep_edges,
    clean_nodes,
    clean_parallel_edges,
    create_edges_ollie,
    create_edges_stanza,
    get_adj_edges,
    get_node_synonyms,
    get_obl_edges,
    get_prep_edges,
    get_unconnected_nodes,
    get_word_types,
    merge_corefs,
    split_node_synonyms,
    split_nodes,
)


class SpeechGraph:
    def __init__(
        self,
        transcript: str,
    ) -> None:

        self.transcript = transcript
        self.graph: Optional[MultiDiGraph] = None

    def process(
        self,
        corenlp_client: Optional[CoreNLPClient] = None,
        openie_client: Optional[OpenIEClient] = None,
    ) -> MultiDiGraph:

        _ = get_settings()

        start_time = time.time()
        print(self.transcript)

        # ------- Clean text -------
        # Need to replace problematic symbols before ANYTHING ELSE, because other tools cannot work with problematic symbols
        text = preprocess.replace_problematic_characters(
            self.transcript, preprocess.PROBLEMATIC_CHARACTER_MAP
        )  # replace ’ with '
        print(text)
        text = preprocess.expand_contractions(
            text, preprocess.CONTRACTION_MAP
        )  # expand it's to it is
        print(text)

        text = preprocess.remove_interjections(
            text, preprocess.INTERJECTIONS, preprocess.CONTRACTION_MAP
        )  # remove Ums and Mmms
        text = preprocess.remove_irrelevant_text(text)
        text = text.strip()  # remove trailing and leading whitespace

        # ------------------------------------------------------------------------------
        # ------- Print cleaned text -------
        print("\n+++ Paragraph: +++ \n\n %s \n\n+++++++++++++++++++" % (text))

        # ------------------------------------------------------------------------------
        # ------------------------------------------------------------------------------
        # ------- Run Stanford CoreNLP (Stanza) -------
        # Annotate and extract with Stanford CoreNLP

        if corenlp_client:
            ex_stanza = corenlp_client.annotate(text)
        else:
            logger.debug("Starting CoreNLP server at %s", f"http://localhost:{settings.netspy_config.server.corenlp.port}")
            with CoreNLPClient(
                properties={
                    "annotators": "tokenize,ssplit,pos,lemma,parse,depparse,coref,openie"
                    # 'pos.model': '/Users/CN/Documents/Projects/Cambridge/cambridge_language_analysis/OpenIE-standalone/target/streams/$global/assemblyOption/$global/streams/assembly/8a3bd51fe5c1bb09a51f326fa358947f6dc78463_8e7f18d9ae73e8daf5ee4d4e11167e10f8827888_da39a3ee5e6b4b0d3255bfef95601890afd80709/edu/stanford/nlp/models/pos-tagger/english-bidirectional/english-bidirectional-distsim.tagger'
                },
                be_quiet=True,
                endpoint = f"http://localhost:{settings.netspy_config.server.corenlp.port}"
            ) as corenlp_client:
                ex_stanza = corenlp_client.annotate(text)

        # ------- Basic Transcript Descriptors -------
        n_tokens, n_sententences, _ = get_transcript_properties(text, ex_stanza)

        # ------------------------------------------------------------------------------
        # ------- Run OpenIE5 (Ollie) -------
        # Ollie can handle more than one sentence at a time, but need to loop through sentences to keep track of sentence index

        if openie_client:

            ex_ollie = {}
            for i, sentence in enumerate(ex_stanza.sentence):
                if len(sentence.token) > 1:
                    print(f"====== Submitting sentence {i+1} tokens =======")
                    sentence_text = (" ").join(
                        [
                            token.originalText
                            for token in sentence.token
                            if token.originalText
                        ]
                    )
                    print("{}".format(sentence_text))

                    extraction = openie_client.extract(sentence_text)

                    ex_ollie[i] = extraction
                else:
                    print(
                        '====== Skipping sentence {}: Sentence has too few tokens: "{}" ======='.format(
                            i + 1,
                            (" ").join(
                                [
                                    token.originalText
                                    for token in sentence.token
                                    if token.originalText
                                ]
                            ),
                        )
                    )

        else:

            with OpenIEClient(quiet=True) as client:

                ex_ollie = {}
                for i, sentence in enumerate(ex_stanza.sentence):
                    if len(sentence.token) > 1:
                        print(f"====== Submitting sentence {i+1} tokens =======")
                        sentence_text = (" ").join(
                            [
                                token.originalText
                                for token in sentence.token
                                if token.originalText
                            ]
                        )
                        print("{}".format(sentence_text))

                        extraction = client.extract(sentence_text)
                        ex_ollie[i] = extraction
                    else:
                        print(
                            '====== Skipping sentence {}: Sentence has too few tokens: "{}" ======='.format(
                                i + 1,
                                (" ").join(
                                    [
                                        token.originalText
                                        for token in sentence.token
                                        if token.originalText
                                    ]
                                ),
                            )
                        )

        print("+++++++++++++++++++\n")

        # --------------------- Create ollie edges ---------------------------------------
        (
            ollie_edges,
            ollie_edges_text_excerpts,
            ollie_one_node_edges,
            ollie_one_node_edges_text_excerpts,
        ) = create_edges_ollie(ex_ollie)

        edges = ollie_edges
        # --------------------- Create stanza edges ---------------------------------------
        stanza_edges, stanza_edges_text_excerpts = create_edges_stanza(
            ex_stanza, be_quiet=False
        )
        # If Ollie was unable to detect any edges, use stanza edges

        if len(ollie_edges) == 0 and len(stanza_edges) != 0:
            edges = stanza_edges
            print(
                "++++ Ollie detected {} edges, but stanza detected {}. Therefore added edges detected by stanza.  ++++".format(
                    len(ollie_edges), len(stanza_edges)
                )
            )
        elif len(ollie_edges) == 0 and len(stanza_edges) == 0:
            print(
                "++++ Ollie detected {} edges and stanza also detected {}. No stanza edges were added. ++++".format(
                    len(ollie_edges), len(stanza_edges)
                )
            )
        else:
            print(
                "++++ Ollie detected {} edges, so no stanza edges were added.  ++++".format(
                    len(ollie_edges)
                )
            )

        # --------------------- Get word types ---------------------------------------
        no_noun, poss_pronouns, dts, nouns, nouns_origtext, adjectives = get_word_types(
            ex_stanza
        )

        adjectives, adjective_edges = get_adj_edges(ex_stanza)

        prepositions, preposition_edges = get_prep_edges(ex_stanza)

        obliques, oblique_edges = get_obl_edges(ex_stanza)

        # --------------------- Add oblique edges ---------------------------------------
        edges = add_obl_edges(edges, oblique_edges)
        # --------------------- Get node name synonyms ---------------------------------------
        node_name_synonyms = get_node_synonyms(ex_stanza, no_noun)
        # --------------------- Split nodes connected by preposition ---------------------------------------
        edges, node_name_synonyms = split_node_synonyms(
            node_name_synonyms, preposition_edges, edges
        )

        edges = split_nodes(edges, preposition_edges, no_noun)
        # --------------------- Merge coreferenced nodes ---------------------------------------
        edges, orig_edges = merge_corefs(
            edges, node_name_synonyms, no_noun, poss_pronouns
        )

        preposition_edges, orig_preposition_edges = merge_corefs(
            preposition_edges, node_name_synonyms, no_noun, poss_pronouns
        )

        adjective_edges, orig_adjective_edges = merge_corefs(
            adjective_edges, node_name_synonyms, no_noun, poss_pronouns
        )

        oblique_edges, orig_oblique_edges = merge_corefs(
            oblique_edges, node_name_synonyms, no_noun, poss_pronouns
        )

        # --------------------- Add adjective edges / preposition edges / unconnected nodes ---------------------------------------
        edges = add_adj_edges(edges, adjective_edges, add_adjective_edges=True)

        edges = add_prep_edges(edges, preposition_edges, add_all_preposition_edges=True)

        unconnected_nodes = get_unconnected_nodes(edges, orig_edges, nouns)

        # --------------------- Clean nodes & edges ---------------------------------------
        edges = clean_nodes(edges, nouns, adjectives)

        edges = clean_parallel_edges(edges)

        # --------------------- Speech Graph ---------------------------------------
        # fig = plt.figure(figsize=(25.6, 9.6))

        # Construct Speech Graph with properties: number of tokens, number of sentences, unconnected nodes as graph property
        G = nx.MultiDiGraph(
            transcript=self.transcript,
            sentences=n_sententences,
            tokens=n_tokens,
            unconnected_nodes=unconnected_nodes,
        )
        # Add Edges
        G.add_edges_from(edges)

        self.graph = G
        return G

    def plot_graph(self, ax=None, **kwargs) -> None:

        if not self.graph:
            raise RuntimeError("self.graph does not exist")

        if not ax:
            _, ax = plt.subplots()

        # Plot Graph and add edge labels
        pos = nx.spring_layout(self.graph)
        nx.draw(
            self.graph,
            pos,
            ax=ax,
            edge_color="black",
            width=1,
            linewidths=1,
            node_size=500,
            node_color="pink",
            alpha=0.9,
            labels={node: node for node in self.graph.nodes()},
            **kwargs,
        )

        edge_labels = dict(
            [
                (
                    (
                        u,
                        v,
                    ),
                    d["relation"],
                )
                for u, v, d in self.graph.edges(data=True)
            ]
        )
        nx.draw_networkx_edge_labels(
            self.graph, pos, edge_labels=edge_labels, font_color="red"
        )

        return ax


class SpeechGraphFile(SpeechGraph):
    def __init__(
        self,
        file: Path,
        output_dir: Optional[Path] = None,
        load_if_exists: bool = True,
    ) -> None:

        self.file = file
        self.output_dir = output_dir

        if not self.check_input_file_exists():
            raise IOError(f"File {self.file} does not exist")

        super().__init__(
            transcript=self.file.read_text(encoding="utf-8"),
        )

        if load_if_exists:
            self.load_graph()

    def check_input_file_exists(self) -> bool:

        return self.file.exists() and self.file.is_file()

    @property
    def output_file(self) -> Optional[Path]:
        if self.output_dir:
            return self.output_dir / (self.file.stem + ".pickle")
        return None

    def output_graph_file(self, output_format: str = "png") -> Path:
        return self.output_file.parent / (self.output_file.stem + "." + output_format)

    @property
    def missing(self) -> bool:
        return not self.output_file.exists()

    def load_graph(self) -> None:

        if not self.missing:
            self.graph = pickle.loads(self.output_file.read_bytes())

    def dump(self, output_dir: Optional[Union[Path, str]] = None) -> None:

        if not output_dir:

            if not self.output_dir:
                raise IOError(
                    "Either initialise SpeechGraphFile with output_dir or pass output_dir argument to dump"
                )

        if not self.graph:
            raise RuntimeError("Graph does not exist")

        # Ensure directory exists
        self.output_dir.mkdir(exist_ok=True)

        with self.output_file.open(mode="wb") as output_f:
            pickle_graph(self.graph, output_f)


def pickle_graph(graph: MultiDiGraph, file, protocol=pickle.HIGHEST_PROTOCOL) -> None:

    pickle.dump(graph, file, protocol)

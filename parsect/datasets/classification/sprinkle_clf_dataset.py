from typing import List, Optional
import collections
import inspect
from parsect.datasets.classification.base_text_classification import (
    BaseTextClassification,
)
from parsect.numericalizer.numericalizer import Numericalizer
from parsect.vocab.vocab import Vocab
import copy
import wrapt
import wasabi


class sprinkle_clf_dataset:
    def __init__(self, vocab_pipe=None, autoset_attrs=True):
        if vocab_pipe is None:
            vocab_pipe = ["word_vocab", "char_vocab"]
        self.autoset_attrs = autoset_attrs
        self.vocab_pipe = vocab_pipe
        self.wrapped_cls = None
        self.init_signature = None
        self.filename = None
        self.word_tokenizer = None
        self.word_instances = None
        self.word_vocab = None
        self.max_num_words = None
        self.word_vocab_store_location = None
        self.word_embedding_type = None
        self.word_embedding_dimension = None
        self.word_numericalizer = None
        self.word_unk_token = None
        self.word_pad_token = None
        self.word_start_token = None
        self.word_end_token = None

    def set_word_vocab(self):
        self.word_instances = self.word_tokenizer.tokenize_batch(self.lines)
        self.word_vocab = Vocab(
            instances=self.word_instances,
            max_num_tokens=self.max_num_words,
            unk_token=self.word_unk_token,
            pad_token=self.word_pad_token,
            start_token=self.word_start_token,
            end_token=self.word_end_token,
            store_location=self.word_vocab_store_location,
            embedding_type=self.word_embedding_type,
            embedding_dimension=self.word_embedding_dimension,
        )
        self.word_numericalizer = Numericalizer(self.word_vocab)
        self.word_vocab.build_vocab()
        self.word_vocab.print_stats()

    def _get_label_stats_table(self):
        all_labels = [label for label in self.labels]
        labels_stats = dict(collections.Counter(all_labels))
        classes = list(set(labels_stats.keys()))
        classes = sorted(classes)
        header = ["label index", "label name", "count"]
        classname2idx = self.wrapped_cls.get_classname2idx()
        rows = [
            (classname2idx[class_], class_, labels_stats[class_]) for class_ in classes
        ]
        formatted = wasabi.table(data=rows, header=header, divider=True)
        return formatted

    @wrapt.decorator
    def __call__(self, wrapped, instance, args, kwargs):
        self.wrapped_cls = wrapped
        self.init_signature = inspect.signature(wrapped.__init__)
        instance = wrapped(*args, **kwargs)
        for idx, (name, param) in enumerate(self.init_signature.parameters.items()):
            if name == "self":
                continue

            # These are values that must be passed
            if name in [
                "filename",
                "dataset_type",
                "max_num_words",
                "max_instance_length",
                "word_vocab_store_location",
            ]:
                try:
                    value = args[idx]
                except IndexError:
                    try:
                        value = kwargs[name]
                    except KeyError:
                        raise ValueError(
                            f"Dataset {self.cls.__name__} should be instantiated with {name}"
                        )
                if self.autoset_attrs:
                    setattr(instance, name, value)
                setattr(self, name, value)

            # These can be passed but have default values
            else:
                try:
                    value = args[idx]
                except IndexError:
                    try:
                        value = kwargs[name]
                    except KeyError:
                        value = param.default

                if self.autoset_attrs:
                    setattr(instance, name, value)
                setattr(self, name, value)

        # set the lines and labels
        self.lines, self.labels = instance.get_lines_labels(self.filename)
        self.word_instances = None
        self.word_vocab = None

        if "word_vocab" in self.vocab_pipe:
            self.set_word_vocab()
            instance.word_vocab = copy.deepcopy(self.word_vocab)
            instance.word_instances = copy.deepcopy(self.word_instances)
            instance.num_instances = len(self.word_instances)

        if "char_vocab" in self.vocab_pipe:
            pass

        label_stats_table = self._get_label_stats_table()
        instance.label_stats_table = label_stats_table

        return instance

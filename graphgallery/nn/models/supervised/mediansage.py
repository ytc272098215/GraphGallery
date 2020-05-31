import numpy as np
import tensorflow as tf
from tensorflow.keras import Model, Input
from tensorflow.keras.layers import Dropout, Softmax
from tensorflow.keras.optimizers import Adam
from tensorflow.keras import regularizers

from graphgallery.nn.layers import MedianAggregator, MedianGCNAggregator
from graphgallery.sequence import SAGEMiniBatchSequence
from graphgallery.utils.graph_utils import construct_neighbors
from graphgallery.nn.models import SupervisedModel
from graphgallery import config


class MedianSAGE(SupervisedModel):
    """


        Arguments:
        ----------
            adj: `scipy.sparse.csr_matrix` (or `csc_matrix`) with shape (N, N)
                The input `symmetric` adjacency matrix, where `N` is the number of nodes 
                in graph.
            x: `np.array` with shape (N, F)
                The input node feature matrix, where `F` is the dimension of node features.
            labels: `np.array` with shape (N,)
                The ground-truth labels for all nodes in graph.
            n_samples (List of positive integer, optional): 
                The number of sampled neighbors for each nodes in each layer. 
                (default :obj: `[10, 5]`, i.e., sample `10` first-order neighbors and 
                `5` sencond-order neighbors, and the radius for `GraphSAGE` is `2`)
            is_normalize_x (Boolean, optional): 
                Whether to use row-normalize for node feature matrix. 
                (default :obj: `True`)
            device (String, optional): 
                The device where the model is running on. You can specified `CPU` or `GPU` 
                for the model. (default: :obj: `CPU:0`, i.e., the model is running on 
                the 0-th device `CPU`)
            seed (Positive integer, optional): 
                Used in combination with `tf.random.set_seed & np.random.seed & random.seed` 
                to create a reproducible sequence of tensors across multiple calls. 
                (default :obj: `None`, i.e., using random seed)
            name (String, optional): 
                Name for the model. (default: name of class)


    """

    def __init__(self, adj, x, labels, n_samples=[15, 3], is_normalize_x=True, 
                 device='CPU:0', seed=None, name=None, **kwargs):

        super().__init__(adj, x, labels, device=device, seed=seed, name=name, **kwargs)

        self.n_samples = n_samples
        self.is_normalize_x = is_normalize_x
        self.preprocess(adj, x)

    def preprocess(self, adj, x):
        adj, x = super().preprocess(adj, x)

        if self.is_normalize_x:
            x = self.normalize_x(x)

        # Dense matrix, shape [n_nodes, max_degree]
        neighbors = construct_neighbors(adj, max_degree=max(self.n_samples))
        # pad with dummy zero vector
        x = np.vstack([x, np.zeros(self.n_features, dtype=config.floatx())])

        with tf.device(self.device):
            x = self.to_tensor(x)
            self.tf_x, self.neighbors = x, neighbors

    def build(self, hiddens=[64], activations=['relu'], dropout=0.5, lr=0.01, l2_norm=5e-4,
              output_normalize=False, aggrator='median'):
        
        assert len(hiddens) == len(self.n_samples)-1
        assert len(hiddens) == len(activations)
        
        with tf.device(self.device):

            if aggrator == 'median':
                Agg = MedianAggregator
            elif aggrator == 'gcn':
                Agg = MedianGCNAggregator
            else:
                raise ValueError(f'Invalid value of `aggrator`, allowed values (`median`, `gcn`), but got `{aggrator}`.')

            x = Input(batch_shape=[None, self.n_features], dtype=self.floatx, name='features')
            nodes = Input(batch_shape=[None], dtype=self.intx, name='nodes')
            neighbors = [Input(batch_shape=[None], dtype=self.intx, name=f'neighbors_{hop}')
                         for hop, n_sample in enumerate(self.n_samples)]

            aggrators = []
            for i, (hid, activation) in enumerate(zip(hiddens, activations)):
                # you can use `GCNAggregator` instead
                aggrators.append(Agg(hid, concat=True, activation=activation,
                                     kernel_regularizer=regularizers.l2(l2_norm)))

            aggrators.append(Agg(self.n_classes))

            h = [tf.nn.embedding_lookup(x, node) for node in [nodes, *neighbors]]
            for agg_i, aggrator in enumerate(aggrators):
                feature_shape = h[0].shape[-1]
                for hop in range(len(self.n_samples)-agg_i):
                    neighbor_shape = [-1, self.n_samples[hop], feature_shape]
                    h[hop] = Dropout(rate=dropout)(aggrator([h[hop], tf.reshape(h[hop+1], neighbor_shape)]))
                h.pop()

            h = h[0]
            if output_normalize:
                h = tf.nn.l2_normalize(h, axis=1)
            output = Softmax()(h)

            model = Model(inputs=[x, nodes, *neighbors], outputs=output)
            model.compile(loss='sparse_categorical_crossentropy', optimizer=Adam(lr=lr), metrics=['accuracy'])

            self.set_model(model)
            self.built = True

    def train_sequence(self, index):
        index = self.to_int(index)
        labels = self.labels[index]
        with tf.device(self.device):
            sequence = SAGEMiniBatchSequence([self.x, index], labels, self.neighbors, n_samples=self.n_samples)
        return sequence

    def predict(self, index):
        super().predict(index)
        logit = []
        index = self.to_int(index)
        with tf.device(self.device):
            data = SAGEMiniBatchSequence([self.x, index], neighbors=self.neighbors, n_samples=self.n_samples)
            for inputs, labels in data:
                output = self.model.predict_on_batch(inputs)
                if tf.is_tensor(output):
                    output = output.numpy()

                logit.append(output)
        logit = np.concatenate(logit, axis=0)
        return logit

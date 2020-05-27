from math import erf, sqrt
import numpy as np
from python_utils.terminal import get_terminal_size
import sys
from typing import Tuple, Union
import warnings
import numba
#print(">"*15)
import time 
try:
    import numba
except ImportError:
    pass

__author__ = 'Valentino Constantinou'
__version__ = '0.3.2'
__license__ = 'Apache License, Version 2.0'


class Utils:

    @staticmethod
    def emit_progress_bar(progress: str, index: int, total: int) -> str:
        """
        A progress bar that is continuously updated in Python's standard
        out.
        :param progress: a string printed to stdout that is updated and later
        returned.
        :param index: the current index of the iteration within the tracked
        process.
        :param total: the total length of the tracked process.
        :return: progress string.
        """

        w, h = get_terminal_size()
        sys.stdout.write("\r")
        block_size = int(total / w)
        if index % block_size == 0:
            progress += "="
        percent = index / total
        sys.stdout.write("[ %s ] %.2f%%" % (progress, percent * 100))
        sys.stdout.flush()
        return progress


class LocalOutlierProbability(object):
    """
    :param data: a Pandas DataFrame or Numpy array of float data
    :param extent: an integer value [1, 2, 3] that controls the statistical 
    extent, e.g. lambda times the standard deviation from the mean (optional, 
    default 3)
    :param n_neighbors: the total number of neighbors to consider w.r.t. each 
    sample (optional, default 10)
    :param cluster_labels: a numpy array of cluster assignments w.r.t. each 
    sample (optional, default None)
    :return:
    """"""

    Based on the work of Kriegel, Kröger, Schubert, and Zimek (2009) in LoOP: 
    Local Outlier Probabilities.
    ----------

    References
    ----------
    .. [1] Breunig M., Kriegel H.-P., Ng R., Sander, J. LOF: Identifying 
           Density-based Local Outliers. ACM SIGMOD
           International Conference on Management of Data (2000).
    .. [2] Kriegel H.-P., Kröger P., Schubert E., Zimek A. LoOP: Local Outlier 
           Probabilities. 18th ACM conference on 
           Information and knowledge management, CIKM (2009).
    .. [3] Goldstein M., Uchida S. A Comparative Evaluation of Unsupervised 
           Anomaly Detection Algorithms for Multivariate Data. PLoS ONE 11(4):
           e0152173 (2016).
    .. [4] Hamlet C., Straub J., Russell M., Kerlin S. An incremental and 
           approximate local outlier probability algorithm for intrusion 
           detection and its evaluation. Journal of Cyber Security Technology 
           (2016). 
    """

    class Validate:

        """
        The Validate class aids in ensuring PyNomaly receives the right set
        of user inputs for proper execution of the Local Outlier Probability
        (LoOP) approach. Depending on the desired behavior, either an
        exception is raised to the user or PyNomaly continues executing
        albeit with some form of user warning.
        """

        """
        Private methods.
        """

        @staticmethod
        def _data(obj: Union['pd.DataFrame', np.ndarray]) -> np.ndarray:
            """
            Validates the input data to ensure it is either a Pandas DataFrame
            or Numpy array.
            :param obj: user-provided input data.
            :return: a vector of values to be used in calculating the local
            outlier probability.
            """
            if obj.__class__.__name__ == 'DataFrame':
                points_vector = obj.values
                return points_vector
            elif obj.__class__.__name__ == 'ndarray':
                points_vector = obj
                return points_vector
            else:
                warnings.warn(
                    "Provided data or distance matrix must be in ndarray "
                    "or DataFrame.",
                    UserWarning)
                if isinstance(obj, list):
                    points_vector = np.array(obj)
                    return points_vector
                points_vector = np.array([obj])
                return points_vector

        def _inputs(self, obj: 'LocalOutlierProbability'):
            """
            Validates the inputs provided during initialization to ensure
            that the needed objects are provided.
            :param obj: a PyNomaly object.
            :return: a boolean indicating whether validation has failed or
            the data, distance matrix, and neighbor matrix.
            """
            if all(v is None for v in [obj.data, obj.distance_matrix]):
                warnings.warn(
                    "Data or a distance matrix must be provided.", UserWarning
                )
                return False
            elif all(v is not None for v in [obj.data, obj.distance_matrix]):
                warnings.warn(
                    "Only one of the following may be provided: data or a "
                    "distance matrix (not both).", UserWarning
                )
                return False
            if obj.data is not None:
                points_vector = self._data(obj.data)
                return points_vector, obj.distance_matrix, obj.neighbor_matrix
            if all(matrix is not None for matrix in [obj.neighbor_matrix,
                                                     obj.distance_matrix]):
                dist_vector = self._data(obj.distance_matrix)
                neigh_vector = self._data(obj.neighbor_matrix)
            else:
                warnings.warn(
                    "A neighbor index matrix and distance matrix must both be "
                    "provided when not using raw input data.", UserWarning
                )
                return False
            if obj.distance_matrix.shape != obj.neighbor_matrix.shape:
                warnings.warn(
                    "The shape of the distance and neighbor "
                    "index matrices must match.", UserWarning
                )
                return False
            elif (obj.distance_matrix.shape[1] != obj.n_neighbors) \
                    or (obj.neighbor_matrix.shape[1] !=
                        obj.n_neighbors):
                warnings.warn("The shape of the distance or "
                              "neighbor index matrix does not "
                              "match the number of neighbors "
                              "specified.", UserWarning)
                return False
            return obj.data, dist_vector, neigh_vector

        @staticmethod
        def _cluster_size(obj) -> bool:
            """
            Validates the cluster labels to ensure that the smallest cluster
            size (number of observations in the cluster) is larger than the
            specified number of neighbors.
            :param obj: a PyNomaly object.
            :return: a boolean indicating whether validation has passed.
            """
            c_labels = obj._cluster_labels()
            for cluster_id in set(c_labels):
                c_size = np.where(c_labels == cluster_id)[0].shape[0]
                if c_size <= obj.n_neighbors:
                    warnings.warn(
                        "Number of neighbors specified larger than smallest "
                        "cluster. Specify a number of neighbors smaller than "
                        "the smallest cluster size (observations in smallest "
                        "cluster minus one).",
                        UserWarning)
                    return False
            return True

        @staticmethod
        def _n_neighbors(obj) -> bool:
            """
            Validates the specified number of neighbors to ensure that it is
            greater than 0 and that the specified value is less than the total
            number of observations.
            :param obj: a PyNomaly object.
            :return: a boolean indicating whether validation has passed.
            """
            if not obj.n_neighbors > 0:
                obj.n_neighbors = 10
                warnings.warn("n_neighbors must be greater than 0."
                              " Fit with " + str(obj.n_neighbors) +
                              " instead.",
                              UserWarning)
                return False
            elif obj.n_neighbors >= obj._n_observations():
                obj.n_neighbors = obj._n_observations() - 1
                warnings.warn(
                    "n_neighbors must be less than the number of observations."
                    " Fit with " + str(obj.n_neighbors) + " instead.",
                    UserWarning)
            return True

        @staticmethod
        def _extent(obj) -> bool:
            """
            Validates the specified extent parameter to ensure it is either 1,
            2, or 3.
            :param obj: a PyNomaly object.
            :return: a boolean indicating whether validation has passed.
            """
            if obj.extent not in [1, 2, 3]:
                warnings.warn(
                    "extent parameter (lambda) must be 1, 2, or 3.",
                    UserWarning)
                return False
            return True

        @staticmethod
        def _missing_values(obj) -> bool:
            """
            Validates the provided data to ensure that it contains no
            missing values.
            :param obj: a PyNomaly object.
            :return: a boolean indicating whether validation has passed.
            """
            if np.any(np.isnan(obj.data)):
                warnings.warn(
                    "Method does not support missing values in input data.",
                    UserWarning)
                return False
            return True

        @staticmethod
        def _fit(obj) -> bool:
            """
            Validates that the model was fit prior to calling the stream()
            method.
            :param obj: a PyNomaly object.
            :return: a boolean indicating whether validation has passed.
            """
            if obj.is_fit is False:
                warnings.warn(
                    "Must fit on historical data by calling fit() prior to "
                    "calling stream(x).",
                    UserWarning)
                return False
            return True

        @staticmethod
        def _no_cluster_labels(obj) -> bool:
            """
            Checks to see if cluster labels are attempting to be used in
            stream() and, if so, calls fit() once again but without cluster
            labels. As PyNomaly does not accept clustering algorithms as input,
            the stream approach does not support clustering.
            :param obj: a PyNomaly object.
            :return: a boolean indicating whether validation has passed.
            """
            if len(set(obj._cluster_labels())) > 1:
                warnings.warn(
                    "Stream approach does not support clustered data. "
                    "Automatically refit using single cluster of points.",
                    UserWarning)
                return False
            return True

    """
    Decorators.
    """

    def accepts(*types):
        """
        A decorator that facilitates a form of type checking for the inputs
        which can be used in Python 3.4-3.7 in lieu of Python 3.5+'s type
        hints.
        :param types: the input types of the objects being passed as arguments
        in __init__.
        :return: a decorator.
        """

        def decorator(f):
            assert len(types) == f.__code__.co_argcount

            def new_f(*args, **kwds):
                for (a, t) in zip(args, types):
                    if type(a).__name__ == 'DataFrame':
                        a = np.array(a)
                    if isinstance(a, t) is False:
                        warnings.warn("Argument %r is not of type %s" % (a, t),
                                      UserWarning)
                opt_types = {
                    'distance_matrix': {
                        'type': types[2]
                    },
                    'neighbor_matrix': {
                        'type': types[3]
                    },
                    'extent': {
                        'type': types[4]
                    },
                    'n_neighbors': {
                        'type': types[5]
                    },
                    'cluster_labels': {
                        'type': types[6]
                    },
                    'use_numba': {
                        'type': types[7]
                    },
                    'progress_bar': {
                        'type': types[8]
                    }
                }
                for x in kwds:
                    opt_types[x]['value'] = kwds[x]
                for k in opt_types:
                    try:
                        if isinstance(opt_types[k]['value'],
                                      opt_types[k]['type']) is False:
                            warnings.warn("Argument %r is not of type %s." % (
                                k, opt_types[k]['type']), UserWarning)
                    except KeyError:
                        pass
                return f(*args, **kwds)

            new_f.__name__ = f.__name__
            return new_f

        return decorator

    @accepts(object, np.ndarray, np.ndarray, np.ndarray, (int, np.integer),
             (int, np.integer), list, bool, bool)
    def __init__(self, data=None, distance_matrix=None, neighbor_matrix=None,
                 extent=3, n_neighbors=10, cluster_labels=None,
                 use_numba=False, progress_bar=False) -> None:
        self.data = data
        self.distance_matrix = distance_matrix
        self.neighbor_matrix = neighbor_matrix
        self.extent = extent
        self.n_neighbors = n_neighbors
        self.cluster_labels = cluster_labels
        self.use_numba = use_numba
        self.points_vector = None
        self.prob_distances = None
        self.prob_distances_ev = None
        self.norm_prob_local_outlier_factor = None
        self.local_outlier_probabilities = None
        self._objects = {}
        self.progress_bar = progress_bar
        self.is_fit = False

        if self.use_numba is True and 'numba' not in sys.modules:
            self.use_numba = False
            warnings.warn(
                "Numba is not available, falling back to pure python mode.",
                UserWarning)

        self.Validate()._inputs(self)
        self.Validate._extent(self)

    """
    Private methods.
    """

    @staticmethod
    def _standard_distance(cardinality: float, sum_squared_distance: float) \
            -> float:
        """
        Calculates the standard distance of an observation.
        :param cardinality: the cardinality of the input observation.
        :param sum_squared_distance: the sum squared distance between all
        neighbors of the input observation.
        :return: the standard distance.
        # """
        division_result = sum_squared_distance / cardinality
        st_dist = sqrt(division_result)
        return st_dist

    @staticmethod
    def _prob_distance(extent: int, standard_distance: float) -> float:
        """
        Calculates the probabilistic distance of an observation.
        :param extent: the extent value specified during initialization.
        :param standard_distance: the standard distance of the input
        observation.
        :return: the probabilistic distance.
        """
        return extent * standard_distance

    @staticmethod
    def _prob_outlier_factor(probabilistic_distance: np.ndarray, ev_prob_dist:
    np.ndarray) -> np.ndarray:
        """
        Calculates the probabilistic outlier factor of an observation.
        :param probabilistic_distance: the probabilistic distance of the
        input observation.
        :param ev_prob_dist:
        :return: the probabilistic outlier factor.
        """
        if np.all(probabilistic_distance == ev_prob_dist):
            return np.zeros(probabilistic_distance.shape)
        else:
            ev_prob_dist[ev_prob_dist == 0.] = 1.e-8
            result = np.divide(probabilistic_distance, ev_prob_dist) - 1.
            return result

    @staticmethod
    def _norm_prob_outlier_factor(extent: float,
                                  ev_probabilistic_outlier_factor: list) \
            -> list:
        """
        Calculates the normalized probabilistic outlier factor of an
        observation.
        :param extent: the extent value specified during initialization.
        :param ev_probabilistic_outlier_factor: the expected probabilistic
        outlier factor of the input observation.
        :return: the normalized probabilistic outlier factor.
        """
        npofs = []
        for i in ev_probabilistic_outlier_factor:
            npofs.append(extent * sqrt(i))
        return npofs

    @staticmethod
    def _local_outlier_probability(plof_val: np.ndarray, nplof_val: np.ndarray) \
            -> np.ndarray:
        """
        Calculates the local outlier probability of an observation.
        :param plof_val: the probabilistic outlier factor of the input
        observation.
        :param nplof_val: the normalized probabilistic outlier factor of the
        input observation.
        :return: the local outlier probability.
        """
        erf_vec = np.vectorize(erf)
        if np.all(plof_val == nplof_val):
            return np.zeros(plof_val.shape)
        else:
            return np.maximum(0, erf_vec(plof_val / (nplof_val * np.sqrt(2.))))

    def _n_observations(self) -> int:
        """
        Calculates the number of observations in the data.
        :return: the number of observations in the input data.
        """
        if self.data is not None:
            return len(self.data)
        return len(self.distance_matrix)

    def _store(self) -> np.ndarray:
        """
        Initializes the storage matrix that includes the input value,
        cluster labels, local outlier probability, etc. for the input data.
        :return: an empty numpy array of shape [n_observations, 3].
        """
        return np.empty([self._n_observations(), 3], dtype=object)

    def _cluster_labels(self) -> np.ndarray:
        """
        Returns a numpy array of cluster labels that corresponds to the
        input labels or that is an array of all 0 values to indicate all
        points belong to the same cluster.
        :return: a numpy array of cluster labels.
        """
        if self.cluster_labels is None:
            if self.data is not None:
                return np.array([0] * len(self.data))
            return np.array([0] * len(self.distance_matrix))
        return np.array(self.cluster_labels)

    @staticmethod
    def _euclidean(vector1: np.ndarray, vector2: np.ndarray) -> np.ndarray:
        """
        Calculates the euclidean distance between two observations in the
        input data.
        :param vector1: a numpy array corresponding to observation 1.
        :param vector2: a numpy array corresponding to observation 2.
        :return: the euclidean distance between the two observations.
        """
        diff = vector1 - vector2
        return np.dot(diff, diff) ** 0.5

    def _assign_distances(self, data_store: np.ndarray) -> np.ndarray:
        """
        Takes a distance matrix, produced by _distances or provided through
        user input, and assigns distances for each observation to the storage
        matrix, data_store.
        :param data_store: the storage matrix that collects information on
        each observation.
        :return: the updated storage matrix that collects information on
        each observation.
        """
        for vec, cluster_id in zip(range(self.distance_matrix.shape[0]),
                                   self._cluster_labels()):
            data_store[vec][0] = cluster_id
            data_store[vec][1] = self.distance_matrix[vec]
            data_store[vec][2] = self.neighbor_matrix[vec]
        return data_store

    @staticmethod
    def _compute_distance_and_neighbor_matrix(
            clust_points_vector: np.ndarray,
            indices: np.ndarray,
            distances: np.ndarray,
            indexes: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, int]:
        """
        This helper method provides the heavy lifting for the _distances
        method and is only intended for use therein. The code has been
        written so that it can make full use of Numba's jit capabilities if
        desired.
        """

        for i in range(clust_points_vector.shape[0]):
            for j in range(i + 1, clust_points_vector.shape[0]):
                p = ((i,), (j,))

                diff = clust_points_vector[p[0]] - clust_points_vector[p[1]]
                d = np.dot(diff, diff) ** 0.5

                idx = indices[0][p[0]]
                idx_max = distances[idx].argmax()

                if d < distances[idx][idx_max]:
                    distances[idx][idx_max] = d
                    indexes[idx][idx_max] = p[1][0]

                idx = indices[0][p[1]]
                idx_max = distances[idx].argmax()

                if d < distances[idx][idx_max]:
                    distances[idx][idx_max] = d
                    indexes[idx][idx_max] = p[0][0]

            yield distances, indexes, i

    def _distances(self, progress_bar: bool = False) -> None:
        """
        Provides the distances between each observation and it's closest
        neighbors. When input data is provided, calculates the euclidean
        distance between every observation. Otherwise, the user-provided
        distance matrix is used.
        :return: the updated storage matrix that collects information on
        each observation.
        """
        '''
        distances = np.full([self._n_observations(), self.n_neighbors], 9e10,
                            dtype=float)
        indexes = np.full([self._n_observations(), self.n_neighbors], 9e10,
                          dtype=float)
        self.points_vector = self.Validate._data(self.data)
        t1 = time.time()
        compute = numba.jit(self._compute_distance_and_neighbor_matrix,
                            cache=True) if self.use_numba else \
            self._compute_distance_and_neighbor_matrix
        t2 = time.time()
        #print("compute:",t2-t1)
        progress = "="
        #print(self._cluster_labels())--> [0 0 0 ... 0]
        #print(set(self._cluster_labels()))
        for cluster_id in set(self._cluster_labels()):
            indices = np.where(self._cluster_labels() == cluster_id)
            clust_points_vector = np.array(
                self.points_vector.take(indices, axis=0)[0],
                dtype=np.float64
            )
            #print(len(clust_points_vector))
            # a generator that yields an updated distance matrix on each loop
            t3 = time.time()
            for c in compute(clust_points_vector, indices, distances, indexes):
                distances, indexes, i = c
                # update the progress bar
                if progress_bar is True:
                    progress = Utils.emit_progress_bar(
                        progress, i+1, clust_points_vector.shape[0])
            t4 = time.time()
            #print("compute:", t4-t3)
        self.distance_matrix = distances
        #print(len(distances))
        #print(len(distances[0]))
        self.neighbor_matrix = indexes
        #print(len(indexes))
        #print(len(indexes[0]))
        '''
        ####################################################################
        #--------------------------------DN's code--------------------------
        # Code does not include cluster or something like that

        
        self.points_vector = self.Validate._data(self.data)
        distances, indexes = self.distance_dn(self.points_vector)
        self.distance_matrix = distances
        #print(len(distances))
        #print(len(distances[0]))
        self.neighbor_matrix = indexes
        #print(len(indexes))
        #print(len(indexes[0]))

        


    def distance_dn(self,point_vector):
        """
        Calculate distances from each point to the remaining points
        """
        data = point_vector
        k = self.n_neighbors
        distance = np.zeros((len(data),k))
        index = np.zeros((len(data),k))
        t1 =time.time()
        for i in range(len(data)):
            data_i = np.array([[data[i][0],data[i][1]]])
            point_arr = np.repeat(data_i,len(data),axis=0)
            diff = (point_arr - data)**2
            dis = (np.sum(diff,axis=1))**0.5
            index[i] = (np.argpartition(dis,k))[0:k]
            distance[i] = dis[(np.argpartition(dis,k))[0:k]]
        #print(distance)
        t2 = time.time()
        #print(t2-t1)
        return distance, index

    def _ssd(self, data_store: np.ndarray) -> np.ndarray:
        """
        Calculates the sum squared distance between neighbors for each
        observation in the input data.
        :param data_store: the storage matrix that collects information on
        each observation.
        :return: the updated storage matrix that collects information on
        each observation.
        """
        self.cluster_labels_u = np.unique(data_store[:, 0])
        ssd_array = np.empty([self._n_observations(), 1])
        for cluster_id in self.cluster_labels_u:
            indices = np.where(data_store[:, 0] == cluster_id)
            cluster_distances = np.take(data_store[:, 1], indices).tolist()
            ssd = np.power(cluster_distances[0], 2).sum(axis=1)
            for i, j in zip(indices[0], ssd):
                ssd_array[i] = j
        data_store = np.hstack((data_store, ssd_array))
        return data_store

    def _standard_distances(self, data_store: np.ndarray) -> np.ndarray:
        """
        Calculated the standard distance for each observation in the input
        data. First calculates the cardinality and then calculates the standard
        distance with respect to each observation.
        :param data_store:
        :param data_store: the storage matrix that collects information on
        each observation.
        :return: the updated storage matrix that collects information on
        each observation.
        """
        cardinality = [self.n_neighbors] * self._n_observations()
        vals = data_store[:, 3].tolist()
        std_distances = []
        for c, v in zip(cardinality, vals):
            std_distances.append(self._standard_distance(c, v))
        return np.hstack((data_store, np.array([std_distances]).T))

    def _prob_distances(self, data_store: np.ndarray) -> np.ndarray:
        """
        Calculates the probabilistic distance for each observation in the
        input data.
        :param data_store: the storage matrix that collects information on
        each observation.
        :return: the updated storage matrix that collects information on
        each observation.
        """
        prob_distances = []
        for i in range(data_store[:, 4].shape[0]):
            prob_distances.append(
                self._prob_distance(self.extent, data_store[:, 4][i]))
        return np.hstack((data_store, np.array([prob_distances]).T))

    def _prob_distances_ev(self, data_store: np.ndarray) -> np.ndarray:
        """
        Calculates the expected value of the probabilistic distance for
        each observation in the input data with respect to the cluster the
        observation belongs to.
        :param data_store: the storage matrix that collects information on
        each observation.
        :return: the updated storage matrix that collects information on
        each observation.
        """
        prob_set_distance_ev = np.empty([self._n_observations(), 1])
        for cluster_id in self.cluster_labels_u:
            indices = np.where(data_store[:, 0] == cluster_id)[0]
            for index in indices:
                nbrhood = data_store[index][2].astype(int)
                nbrhood_prob_distances = np.take(data_store[:, 5],
                                                 nbrhood).astype(float)
                nbrhood_prob_distances_nonan = nbrhood_prob_distances[
                    np.logical_not(np.isnan(nbrhood_prob_distances))]
                prob_set_distance_ev[index] = \
                    nbrhood_prob_distances_nonan.mean()
        self.prob_distances_ev = prob_set_distance_ev
        data_store = np.hstack((data_store, prob_set_distance_ev))
        return data_store

    def _prob_local_outlier_factors(self,
                                    data_store: np.ndarray) -> np.ndarray:
        """
        Calculates the probabilistic local outlier factor for each
        observation in the input data.
        :param data_store: the storage matrix that collects information on
        each observation.
        :return: the updated storage matrix that collects information on
        each observation.
        """
        return np.hstack(
            (data_store,
             np.array([np.apply_along_axis(self._prob_outlier_factor, 0,
                                           data_store[:, 5],
                                           data_store[:, 6])]).T))

    def _prob_local_outlier_factors_ev(self,
                                       data_store: np.ndarray) -> np.ndarray:
        """
        Calculates the expected value of the probabilistic local outlier factor
        for each observation in the input data with respect to the cluster the
        observation belongs to.
        :param data_store: the storage matrix that collects information on
        each observation.
        :return: the updated storage matrix that collects information on
        each observation.
        """
        prob_local_outlier_factor_ev_dict = {}
        for cluster_id in self.cluster_labels_u:
            indices = np.where(data_store[:, 0] == cluster_id)
            prob_local_outlier_factors = np.take(data_store[:, 7],
                                                 indices).astype(float)
            prob_local_outlier_factors_nonan = prob_local_outlier_factors[
                np.logical_not(np.isnan(prob_local_outlier_factors))]
            prob_local_outlier_factor_ev_dict[cluster_id] = (
                    np.power(prob_local_outlier_factors_nonan, 2).sum() /
                    float(prob_local_outlier_factors_nonan.size)
            )
        data_store = np.hstack(
            (data_store, np.array([[prob_local_outlier_factor_ev_dict[x] for x
                                    in data_store[:, 0].tolist()]]).T))
        return data_store

    def _norm_prob_local_outlier_factors(self, data_store: np.ndarray) \
            -> np.ndarray:
        """
        Calculates the normalized probabilistic local outlier factor for each
        observation in the input data.
        :param data_store: the storage matrix that collects information on
        each observation.
        :return: the updated storage matrix that collects information on
        each observation.
        """
        return np.hstack((data_store, np.array([self._norm_prob_outlier_factor(
            self.extent, data_store[:, 8].tolist())]).T))

    def _local_outlier_probabilities(self,
                                     data_store: np.ndarray) -> np.ndarray:
        """
        Calculates the local outlier probability for each observation in the
        input data.
        :param data_store: the storage matrix that collects information on
        each observation.
        :return: the updated storage matrix that collects information on
        each observation.
        """
        return np.hstack(
            (data_store,
             np.array([np.apply_along_axis(self._local_outlier_probability, 0,
                                           data_store[:, 7],
                                           data_store[:, 9])]).T))

    """
    Public methods
    """

    def fit(self) -> 'LocalOutlierProbability':

        """
        Calculates the local outlier probability for each observation in the
        input data according to the input parameters extent, n_neighbors, and
        cluster_labels.
        :return: self, which contains the local outlier probabilities as
        self.local_outlier_probabilities.
        """
        t1 = time.time()
        self.Validate._n_neighbors(self)
        if self.Validate._cluster_size(self) is False:
            sys.exit()
        if self.data is not None and self.Validate._missing_values(
                self) is False:
            sys.exit()

        t2 = time.time()
        store = self._store()
        if self.data is not None:
            self._distances(progress_bar=self.progress_bar)
        t3 = time.time()
        store = self._assign_distances(store)
        t4 = time.time()
        store = self._ssd(store)
        t5 = time.time()
        store = self._standard_distances(store)
        t6 = time.time()
        store = self._prob_distances(store)
        t7 = time.time()
        self.prob_distances = store[:, 5]
        store = self._prob_distances_ev(store)
        t8 = time.time()
        store = self._prob_local_outlier_factors(store)
        t9 = time.time()
        store = self._prob_local_outlier_factors_ev(store)
        t10 = time.time()
        store = self._norm_prob_local_outlier_factors(store)
        t11 = time.time()
        self.norm_prob_local_outlier_factor = store[:, 9].max()
        store = self._local_outlier_probabilities(store)
        self.local_outlier_probabilities = store[:, 10]
        t12 = time.time()
        self.is_fit = True

        print("Time of LoOP training")
        print("-"*35)
        print("validation:",t2-t1)
        print("_distances:",t3-t2)
        print("_assign_distances:",t4-t3)
        print("_ssd:",t5-t4)
        print("_standard_distances:",t6-t5)
        print("_prob_distances:",t7-t6)
        print("_prob_distances_ev:",t8-t7)
        print("_prob_local_outlier_factors:",t9-t8)
        print("_prob_local_outlier_factors_ev:",t10-t9)
        print("_norm_prob_local_outlier_factors:",t11-t10)
        print("_local_outlier_probabilities",t12-t11)
        print("Total training time:", t12-t1)
        print("-"*35)
        return self

    def stream(self, x: np.ndarray) -> np.ndarray:

        """
        Calculates the local outlier probability for an individual sample
        according to the input parameters extent, n_neighbors, and
        cluster_labels after first calling fit(). Observations are assigned
        a local outlier probability against the mean of expected values of
        probabilistic distance and the normalized probabilistic outlier
        factor from the earlier model, provided when calling fit().
        distance
        :param x: an observation to score for its local outlier probability.
        :return: the local outlier probability of the input observation.
        """
        t1 = time.time()
        orig_cluster_labels = None
        if self.Validate._no_cluster_labels(self) is False:
            orig_cluster_labels = self.cluster_labels
            self.cluster_labels = np.array([0] * len(self.data))

        if self.Validate._fit(self) is False:
            self.fit()
        t2= time.time()
        point_vector = self.Validate._data(x)
        distances = np.full([1, self.n_neighbors], 9e10, dtype=float)
        if self.data is not None:
            matrix = self.points_vector
        else:
            matrix = self.distance_matrix
        t3 = time.time()
        '''
        for p in range(0, matrix.shape[0]):
            if self.data is not None:
                d = self._euclidean(matrix[p, :], point_vector)
            else:
                d = point_vector
            idx_max = distances[0].argmax()
            if d < distances[0][idx_max]:
                distances[0][idx_max] = d
        '''
        ########## Use distance_point_dn() thay cho vòng for
        distances = self.distance_point_dn(matrix,point_vector)
        t4 = time.time()


        ssd = np.power(distances, 2).sum()
        t5 = time.time()
        std_dist = np.sqrt(np.divide(ssd, self.n_neighbors))
        t6 = time.time()
        prob_dist = self._prob_distance(self.extent, std_dist)
        t7 = time.time()
        plof = self._prob_outlier_factor(np.array(prob_dist),
                                         np.array(
                                             self.prob_distances_ev.mean())
                                         )
        t8 = time.time()
        loop = self._local_outlier_probability(
            plof, self.norm_prob_local_outlier_factor)
        t9 = time.time()
        if orig_cluster_labels is not None:
            self.cluster_labels = orig_cluster_labels

        #print("Validate:",t2-t1)
        #print("matrix:",t3-t2)
        #print("distances:",t4-t3)
        #print("ssd:",t5-t4)
        #print("std_dist",t6-t5)
        #print("prob_dist:",t7-t6)
        #print("plof:",t8-t7)
        #print("loop:",t9-t8)
        print("Total test time:",t9-t1)
        return loop

    def distance_point_dn(self,matrix,point_vector):
        #Return a distance array of k nearest neighbor from a point to data
        data = matrix
        k = self.n_neighbors
        distance = np.zeros((1,k))
        #index = np.zeros((len(data),k))
        t1 =time.time()
        data_i = np.array([[point_vector[0],point_vector[1]]])
        point_arr = np.repeat(data_i,len(data),axis=0)
        diff = (point_arr - data)**2
        dis = (np.sum(diff,axis=1))**0.5
        #index[i] = (np.argpartition(dis,k))[0:k]
        distance = dis[(np.argpartition(dis,k))[0:k]]
        return distance

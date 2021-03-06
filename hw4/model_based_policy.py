import tensorflow as tf
import numpy as np
from sklearn.metrics import mean_squared_error
import utils


class ModelBasedPolicy(object):

    def __init__(self,
                 env,
                 init_dataset,
                 horizon=15,
                 num_random_action_selection=4096,
                 nn_layers=1):
        self._cost_fn = env.cost_fn
        self._state_dim = env.observation_space.shape[0]
        self._action_dim = env.action_space.shape[0]
        self._action_space_low = env.action_space.low
        self._action_space_high = env.action_space.high
        self._init_dataset = init_dataset
        self._horizon = horizon
        self._num_random_action_selection = num_random_action_selection
        self._nn_layers = nn_layers
        self._learning_rate = 1e-3
        print("ModelBasedPolicy - before settup graph")
        self._sess, self._state_ph, self._action_ph, self._next_state_ph,\
            self._next_state_pred, self._loss, self._optimizer, self._best_action = self._setup_graph()
        self.count = 0
        print("ModelBasedPolicy - after settup graph")

    def _setup_placeholders(self):
        """
            Creates the placeholders used for training, prediction, and action selection

            returns:
                state_ph: current state
                action_ph: current_action
                next_state_ph: next state

            implementation details:
                (a) the placeholders should have 2 dimensions,
                    in which the 1st dimension is variable length (i.e., None)
        """
        state_ph = tf.placeholder(tf.float32, [None, self._state_dim])
        action_ph = tf.placeholder(tf.float32, [None, self._action_dim])
        next_state_ph = tf.placeholder(tf.float32, [None, self._state_dim])


        return state_ph, action_ph, next_state_ph

    def _dynamics_func(self, state, action, reuse=True):
        """
            Takes as input a state and action, and predicts the next state

            returns:
                next_state_pred: predicted next state

            implementation details (in order):
                (a) Normalize both the state and action by using the statistics of self._init_dataset and
                    the utils.normalize function
                (b) Concatenate the normalized state and action
                (c) Pass the concatenated, normalized state-action tensor through a neural network with
                    self._nn_layers number of layers using the function utils.build_mlp. The resulting output
                    is the normalized predicted difference between the next state and the current state
                (d) Unnormalize the delta state prediction, and add it to the current state in order to produce
                    the predicted next state

        """
        print("ModelBasedPolicy - before _dynamics_func")
        ### PROBLEM 1
        ##############
        ### part a ###Normalize state and action by using statistics of self._init_dataset
        ##############
        s_mean = self._init_dataset.state_mean
        a_mean = self._init_dataset.action_mean
        s_std = self._init_dataset.state_std
        a_std = self._init_dataset.action_std
        state_d_m = self._init_dataset.delta_state_mean
        state_d_s  = self._init_dataset.delta_state_std
        normalize_state = utils.normalize(state,s_mean,s_std)
        normalize_action = utils.normalize(action,a_mean,a_std)

        ##############
        ### part b ### Concatenate state and action
        ##############
        s_a = tf.concat([normalize_state,normalize_action], axis = 1)
        # s_a = np.concatenate((normalize_state,normalize_action),axis = None)
        # d = s_a.shape
        ##############
        ### part c ### Generate NN
        ##############
        # print ("generate the NN")
        # s_a_placeholder = tf.placeholder(tf.float32, [None,d[0]])
        print ("generate the NN")
        next_state_prediction = utils.build_mlp(s_a,
                      self._state_dim,
                      "nn_prediciton",
                      n_layers=self._nn_layers,
                      reuse = reuse)

        print("finish gen NN")

        ##############
        ### pard d ###
        ##############
        delta_state = utils.unnormalize(next_state_prediction, state_d_m, state_d_s)
        next_state_pred = state+delta_state
        print("ModelBasedPolicy - after _dynamics_func")
        return next_state_pred

    def _setup_training(self, state_ph, next_state_ph, next_state_pred):
        """
            Takes as input the current state, next state, and predicted next state, and returns
            the loss and optimizer for training the dynamics model

            returns:
                loss: Scalar loss tensor
                optimizer: Operation used to perform gradient descent

            implementation details (in order):
                (a) Compute both the actual state difference and the predicted state difference
                (b) Normalize both of these state differences by using the statistics of self._init_dataset and
                    the utils.normalize function
                (c) The loss function is the mean-squared-error between the normalized state difference and
                    normalized predicted state difference
                (d) Create the optimizer by minimizing the loss using the Adam optimizer with self._learning_rate

        """
        print("ModelBasedPolicy - before _setup_training")
        ### PROBLEM 1
        ##############
        ### part a ###
        ##############
        #...s_d : state difference
        act_s_d = next_state_ph - state_ph
        pred_s_d = next_state_pred - state_ph

        ##############
        ### part b ###
        ##############
        #...d_m: delta_mean
        #...d_s: delta_std
        state_d_m = self._init_dataset.delta_state_mean
        state_d_s  = self._init_dataset.delta_state_std
        norm_act_s_d = utils.normalize(act_s_d,state_d_m,state_d_s)
        norm_pred_s_d = utils.normalize(pred_s_d,state_d_m,state_d_s)

        ##############
        ### part c ###
        ##############
        loss = tf.losses.mean_squared_error(norm_act_s_d, norm_pred_s_d)

        ##############
        ### part d ###
        ##############
        optimizer = tf.train.AdamOptimizer(self._learning_rate).minimize(loss)
        print("ModelBasedPolicy - after _setup_training")
        return loss, optimizer

    def _setup_action_selection(self, state_ph):
        """
            Computes the best action from the current state by using randomly sampled action sequences
            to predict future states, evaluating these predictions according to a cost function,
            selecting the action sequence with the lowest cost, and returning the first action in that sequence

            returns:
                best_action: the action that minimizes the cost function (tensor with shape [self._action_dim])

            implementation details (in order):
                (a) We will assume state_ph has a batch size of 1 whenever action selection is performed
                (b) Randomly sample uniformly self._num_random_action_selection number of action sequences,
                    each of length self._horizon
                (c) Starting from the input state, unroll each action sequence using your neural network
                    dynamics model
                (d) While unrolling the action sequences, keep track of the cost of each action sequence
                    using self._cost_fn
                (e) Find the action sequence with the lowest cost, and return the first action in that sequence

            Hints:
                (i) self._cost_fn takes three arguments: states, actions, and next states. These arguments are
                    2-dimensional tensors, where the 1st dimension is the batch size and the 2nd dimension is the
                    state or action size
                (ii) You should call self._dynamics_func and self._cost_fn a total of self._horizon times
                (iii) Use tf.random_uniform(...) to generate the random action sequences

        """
        ### PROBLEM 2
        ### YOUR CODE HERE

        ##############
        ### part a ###
        ##############
        print("_______________________________________________________________")
        next_states = []
        end_rollout = []
        cost = []
        random_actions = tf.random_uniform([self._num_random_action_selection,self._horizon,self._action_dim], minval=self._action_space_low,maxval=self._action_space_high)
        # for i in range(self._num_random_action_selection):
        #     for j in range(self._horizon)
        print(tf.manip.reshape(random_actions[0,0],[1,6]))
        print("_____________________________start__________________________________")
        print(self._dynamics_func(state_ph,tf.manip.reshape(random_actions[0,0],[1,6]),reuse=True))
        count = 0
        for i in range(self._num_random_action_selection-1):
            for j in range(self._horizon):
                if j == 0:
                    next_states.append(self._dynamics_func(state_ph,
                                                            tf.manip.reshape(random_actions[i,j],[1,6]),
                                                            reuse=True))
                    cost.append(self._cost_fn(state_ph,
                                            tf.manip.reshape(random_actions[i,j],[1,6]),
                                            next_states[count]))
                else:
                    next_states.append(self._dynamics_func(next_states[count-1],
                                                            tf.manip.reshape(random_actions[i,j],[1,6]),
                                                            reuse=True))
                    cost.append(self._cost_fn(state_ph,
                                            tf.manip.reshape(random_actions[i,j],[1,6]),
                                            next_states[count]))
            count +=1
        print("______________________end cost & next_states___________________________")
        final_cost = []
        for i in range(self._num_random_action_selection):
            final_cost.append(tf.sum(cost, [self._horizon*i,self._horizon*(i +1)]))
        best_action_sequence = tf.argmax(final_cost)
        best_action = random_actions[best_action_sequence,0]
        best_action = tf.manip.reshape(best_action,[1,self._action_dim])
        return best_action
        # return random_actions[0]

    def _setup_graph(self):
        """
        Sets up the tensorflow computation graph for training, prediction, and action selection

        The variables returned will be set as class attributes (see __init__)
        """
        sess = tf.Session()
        print("ModelBasedPolicy - before _setup_graph")
        ### PROBLEM 1

        ##############
        ### part a ### -> generate tf.placeholder
        ##############
        state_ph, action_ph, next_state_ph = self._setup_placeholders()

        ##############
        ### part b ### -> settup training
        ##############
        next_state_pred = self._dynamics_func(state_ph, action_ph, False)

        ##############
        ### part c ### -> settup prediction
        ##############
        loss, optimizer = self._setup_training(state_ph, next_state_ph, next_state_pred)


        ### PROBLEM 2
        ### YOUR CODE HERE
        best_action = self._setup_action_selection(state_ph)
        # best_action = None

        sess.run(tf.global_variables_initializer())
        print("ModelBasedPolicy - after _setup_graph")
        return sess, state_ph, action_ph, next_state_ph, \
                next_state_pred, loss, optimizer, best_action

    def train_step(self, states, actions, next_states):
        """
        Performs one step of gradient descent

        returns:
            loss: the loss from performing gradient descent
        """
        print("ModelBasedPolicy - before train_step")
        ### PROBLEM 1
        self._sess.run(self._optimizer, feed_dict={ self._state_ph: states,
                                                self._action_ph: actions,
                                                self._next_state_ph: next_states
                                                })
        loss = self._sess.run(self._loss,  feed_dict={ self._state_ph: states,
                                                self._action_ph: actions,
                                                self._next_state_ph: next_states
                                                })
        print("ModelBasedPolicy - after train_step")
        return loss

    def predict(self, state, action):
        """
        Predicts the next state given the current state and action

        returns:
            next_state_pred: predicted next state

        implementation detils:
            (i) The state and action arguments are 1-dimensional vectors (NO batch dimension)
        """
        print("ModelBasedPolicy - before predict")
        assert np.shape(state) == (self._state_dim,)
        assert np.shape(action) == (self._action_dim,)

        ### PROBLEM 1
        print("______________")

        state = state.reshape(1,20)
        action = action.reshape(1,6)

        next_state_pred =  self._sess.run(  self._next_state_pred,
                                            feed_dict = {self._state_ph: state,
                                                self._action_ph: action
                                                })

        next_state_pred = next_state_pred[0]
        assert np.shape(next_state_pred) == (self._state_dim,)
        # action_ph = tf.placeholder(tf.int32, [self._action_dim])
        # random = tf.random_uniform(action_ph)

        return next_state_pred


    def get_action(self, state):
        """
        Computes the action that minimizes the cost function given the current state

        returns:
            best_action: the best action
        """
        assert np.shape(state) == (self._state_dim,)

        ### PROBLEM 2
        ### YOUR CODE HERE
        state = state.reshape(1,20)
        best_action = self._sess.run(self._best_action,feed_dict = {self._state_ph: state})

        assert np.shape(best_action) == (self._action_dim,)
        return best_action

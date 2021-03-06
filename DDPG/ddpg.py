import os
import sys
import gym
import tensorflow as tf
import numpy as np
import time
import keras
import argparse

sys.path.insert(0, '../')
from utils.noise import OrnsteinUhlenbeckActionNoise
from utils.experience_replay import ExpReplay
from utils.models import Actor, Critic
from utils.tensorboard_utils import add_histogram

class DDPG:
    
    def __init__ (
        self,
        env,
        state_dim,
        action_dim,
        action_low,
        action_high,
        replaybuffer,
        warm_steps = 50000,
        tau = 0.001
    ):
        
        self.env = env
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.action_low = action_low
        self.action_high = action_high
        self.warm_steps = warm_steps
        self.replay = replaybuffer
        self.tau = tau
          
        self.state_ph = tf.placeholder(tf.float32, ((None,) + state_dim))
        self.action_ph = tf.placeholder(tf.float32, ((None,) + action_dim))
        self.target_ph = tf.placeholder(tf.float32, (None, 1))  
        self.action_grads_ph = tf.placeholder(tf.float32, ((None,) + action_dim)) 
        self.is_training_ph = tf.placeholder_with_default(True, shape=None)
            
        self.critic = Critic(
            self.state_ph, self.action_ph, state_dim, action_dim)
        self.critic_target = Critic(
            self.state_ph, self.action_ph, state_dim, action_dim)    
            
        self.actor = Actor(
            self.state_ph, state_dim, action_dim, self.action_low, self.action_high)
        self.actor_target = Actor(
            self.state_ph, state_dim, action_dim, self.action_low, self.action_high)
        
        self.critic_train_step = self.critic.train_step(self.target_ph)
        self.actor_train_step = self.actor.train_step(self.action_grads_ph)
        
        self.update_critic_target = self.update_target_network(
            self.critic.network_params, self.critic_target.network_params, self.tau)
        self.update_actor_target = self.update_target_network(
            self.actor.network_params, self.actor_target.network_params, self.tau)
        
    def update_target_network(self, network_params, target_network_params, tau):     
        
        op_holder = []
        for from_var,to_var in zip(network_params, target_network_params):
            op_holder.append(to_var.assign((tf.multiply(from_var, tau) + tf.multiply(to_var, 1. - tau))))        

        return op_holder
        
    def train(self, env_name, train_eps = 5000, noise_scale = 0.1):
        
        start_ep = 0
        start_time = str(time.time())
        
        sess.run(tf.global_variables_initializer())   
        writer = tf.summary.FileWriter(os.path.join('logs', env_name.lower(), start_time))
        
        state = self.env.reset()
        noise_scaling = noise_scale * (self.action_high - self.action_low)
     
        for random_step in range(1, self.warm_steps + 1):
            action = self.env.action_space.sample()
            next_state, reward, done, _ = self.env.step(action)
            self.replay.add(state, action, reward, next_state, done)
            
            state = next_state
            if done:
                state = self.env.reset()
        
        exploration_noise = OrnsteinUhlenbeckActionNoise(mu=np.zeros(self.action_dim))

        for train_ep in range(1, train_eps + 1):
            start_time_ep = time.process_time()  
            state = self.env.reset()
            
            exploration_noise.reset()
            train_step = 0
            episode_reward = 0
            ep_done = False

            while not ep_done:
                train_step += 1           

                action = sess.run(self.actor.output, {self.state_ph: state[None]})[0]
                noise = exploration_noise() * noise_scaling 
                
                action += noise
                next_state, reward, done, _ = self.env.step(action)
                self.replay.add(state, action, reward, next_state, done)

                episode_reward += reward
                states_batch, actions_batch, rewards_batch, next_states_batch, done_batch = self.replay.sample(64) 

                # Critic training step    
                future_action = sess.run(
                    self.actor_target.output, {self.state_ph: next_states_batch})  
                future_Q = sess.run(
                    self.critic_target.output, {self.state_ph: next_states_batch, self.action_ph: future_action})[:,0]   
                future_Q[done_batch] = 0
                targets = rewards_batch + (future_Q * 0.99)
                sess.run(
                    self.critic_train_step, {self.state_ph:states_batch, self.action_ph:actions_batch, self.target_ph:np.expand_dims(targets, 1)})   

                # Actor training step
                actor_actions = sess.run(
                    self.actor.output, {self.state_ph:states_batch})
                action_grads = sess.run(
                    self.critic.action_grads, {self.state_ph:states_batch, self.action_ph:actor_actions})
                sess.run(self.actor_train_step, {self.state_ph:states_batch, self.action_grads_ph:action_grads[0]})

                # Update target networks
                sess.run(self.update_critic_target)
                sess.run(self.update_actor_target)
                
                state = next_state

                if done or train_step == 1000:
                    start_ep += 1
                    summary=tf.Summary()
                    summary.value.add(tag='Episode Rewards', simple_value = episode_reward)
                    writer.add_summary(summary, start_ep)

                    add_histogram(writer, 'Noise', noise, start_ep)
                    print('Episode {}- Rewards: {} - Process Time: {}'.format(
                        start_ep, episode_reward, time.process_time()-start_time_ep))
                    
                    ep_done = True

        self.env.close()

    def evaluate(self, env, episodes = 20, render = False, monitor = False):
        rewards = []

        for e in range(episodes):
            reward = 0
            if monitor:
                env = gym.wrappers.Monitor(
                    env,
                    os.path.join('video', str(time.time())),
                    video_callable=lambda episode_id: True,
                    force=True)
            s = env.reset()
            while True:
                action = sess.run(self.actor.output, {self.state_ph: s[None]})[0]
                if render:
                    env.render()
                next_state, r, done, _ = env.step(action)
                reward += r

                if done:
                    print('Evaluation {} - Reward: {}'.format(e, reward))
                    rewards.append(reward)
                    break

                s = next_state
            env.close()
        mean_rewards = np.mean(rewards)
        print('Mean Rewards: {}'.format(mean_rewards))
        return mean_rewards
        

if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-env', '--enviroment', default='Pendulum-v0')
    parser.add_argument('-noise', '--noise', default=0.1)
    parser.add_argument('-e', '--exp_replay', default=5e6)
    parser.add_argument('-t', '--train_eps', default=1000)
    args = vars(parser.parse_args())

    sess = tf.InteractiveSession()
    keras.backend.set_session(sess)

    env_name = args['enviroment']
    env = gym.make(env_name)

    state_dim = env.observation_space.shape
    action_dim = env.action_space.shape
    high = env.action_space.high
    low = env.action_space.low

    replaybuffer = ExpReplay(int(args['exp_replay']))
    ddpg = DDPG(env, state_dim, action_dim, high, low, replaybuffer)
    ddpg.train(env_name, int(args['train_eps']), noise_scale=float(args['noise']))

    ddpg.evaluate(env, render = True, monitor = True)
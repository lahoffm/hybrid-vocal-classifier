"""
model selection:
trains models that classify birdsong syllables,
using algorithms and other parameters specified in config file
"""

#from standard library
import sys
import os
import glob
from datetime import datetime

# from dependencies
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.externals import joblib

#from hvc
from .parseconfig import parse_config
from .utils import filter_samples, grab_n_samples_by_song, get_acc_by_label


def select(config_file):
    """main function that runs model selection.
    Doesn't return anything, saves model files and summary file.
    
    Parameters
    ----------
    config_file  : string
        filename of YAML file that configures feature extraction    
    """

    select_config = parse_config(config_file,'select')
    print('Parsed select config.')

    todo_list = select_config['todo_list']

    for ind, todo in enumerate(todo_list):

        print('Completing item {} of {} in to-do list'.format(ind+1,len(todo_list)))

        timestamp = datetime.now().strftime('%y%m%d_%H%M')
        output_dir = todo['output_dir'] + 'select_output_' + timestamp
        if not os.path.isdir(output_dir):
            os.mkdir(output_dir)
        output_filename = os.path.join(output_dir,'select_output_' + timestamp)

        if 'models' in todo:
            model_list = todo['models']
        else:
            model_list = select_config['models']

        for model_dict in model_list:
            # import models objects from sklearn + keras if not imported already
            if model_dict['model'] == 'svm':
                if 'SVC' not in locals():
                    from sklearn.svm import SVC

            elif model_dict['model'] == 'knn':
                if 'neighbors' not in locals():
                    from sklearn import neighbors

            elif model_dict['model'] == 'flatwindow':
                if 'flatwindow' not in locals():
                    from hvc.neuralnet.models import flatwindow

        if 'num_test_samples' in todo:
            num_test_samples = todo['num_test_samples']
        else:
            num_test_samples = select_config['num_test_samples']

        if 'num_train_samples' in todo:
            num_train_samples_list = todo['num_train_samples']
        else:
            num_train_samples_list = select_config['num_train_samples']

        if 'num_replicates' in todo:
            num_replicates = todo['num_replicates']
        else:
            num_replicates = select_config['num_replicates']

        feature_file = joblib.load(todo['feature_file'])
        labels = np.asarray(feature_file['labels'])
        # call grab_n_samples this first time to get indices for test/validation set
        # and a list of song IDs from which we will draw the training set indices below
        test_IDs, train_song_ID_list = grab_n_samples_by_song(feature_file['song_IDs'],
                                                              feature_file['labels'],
                                                              num_test_samples,
                                                              return_popped_songlist=True)
        labels_test = labels[test_IDs]

        score_arr = np.zeros((len(num_train_samples_list),
                           len(range(num_replicates)),
                           len(model_list)))
        avg_acc_arr = np.zeros((len(num_train_samples_list),
                                len(range(num_replicates)),
                                len(model_list)))
        pred_labels_arr = np.empty((len(num_train_samples_list),
                                    len(range(num_replicates)),
                                    len(model_list)),
                                   dtype='O')
        train_IDs_arr = np.empty((len(num_train_samples_list),
                                    len(range(num_replicates))),
                                   dtype='O')

        for num_samples_ind, num_train_samples in enumerate(num_train_samples_list):
            for replicate in range(num_replicates):
                print('Training models with {0} samples, replicate #{1}'
                      .format(num_train_samples, replicate))
                # here we call grab_n_samples again with the train_song_ID_list
                # from above. currently each fold is a random grab without
                # anything like k-folds.
                # For testing on large datasets this is okay but in situations
                # where we're data-limited it's less than ideal, the whole point
                # is to not have to hand-label a large data set
                train_IDs = grab_n_samples_by_song(feature_file['song_IDs'],
                                                   feature_file['labels'],
                                                   num_train_samples,
                                                   song_ID_list=train_song_ID_list)
                train_IDs_arr[num_samples_ind, replicate] = train_IDs
                labels_train = labels[train_IDs]
                for model_ind, model_dict in enumerate(model_list):

                    #if-elif that switches based on model type, start with sklearn models
                    if model_dict['model'] in ['svm', 'knn']:
                        if model_dict['model'] == 'svm':
                            print('training svm. ', end='')
                            clf = SVC(C=model_dict['hyperparameters']['C'],
                                      gamma=model_dict['hyperparameters']['gamma'],
                                      decision_function_shape='ovr')
                        elif model_dict['model'] == 'knn':
                            print('training knn. ', end='')
                            clf = neighbors.KNeighborsClassifier(model_dict['hyperparameters']['k'],
                                                                 'distance')

                        if model_dict['feature_list_indices'] == 'all':
                            feature_inds = np.ones((
                                feature_file['features_arr_column_IDs'].shape[-1],)).astype(bool)
                        else:
                            feature_inds = np.in1d(feature_file['features_arr_column_IDs'],
                                                   model_dict['feature_list_indices'])

                        #use 'advanced indexing' to get only sample rows and only feature models
                        features_train = feature_file['features'][train_IDs[:, np.newaxis],
                                                                  feature_inds]
                        scaler = StandardScaler()
                        features_train = scaler.fit_transform(features_train)

                        features_test = feature_file['features'][test_IDs[:,np.newaxis],
                                                                 feature_inds]
                        features_test = scaler.transform(features_test)

                        print('fitting model. ', end='')
                        clf.fit(features_train, labels_train)
                        score = clf.score(features_test, labels_test)
                        print('score on test set: {:05.4f} '.format(score), end='')
                        score_arr[num_samples_ind, replicate, model_ind] = score
                        pred_labels = clf.predict(features_test)
                        pred_labels_arr[num_samples_ind, replicate, model_ind] = pred_labels
                        acc_by_label, avg_acc = get_acc_by_label(labels_test,
                                                                 pred_labels,
                                                                 feature_file['labelset'])
                        print(', average accuracy on test set: {:05.4f}'.format(avg_acc))
                        avg_acc_arr[num_samples_ind, replicate, model_ind] = avg_acc
                        model_output_dir = os.path.join(output_dir,model_dict['model'])
                        if not os.path.isdir(model_output_dir):
                            os.mkdir(model_output_dir)
                        model_fname_str = '{0}_{1}samples_replicate{2}'.format(model_dict['model'],
                                                                               num_train_samples,
                                                                               replicate)
                        model_filename = os.path.join(model_output_dir, model_fname_str)
                        if model_dict['feature_list_indices'] == 'all':
                            model_feature_list = feature_file['feature_list']
                        else:
                            model_feature_list = [feature_file['feature_list'][ind]
                                                  for ind in model_dict['feature_list_indices']]
                        model_output_dict = {
                            'model_feature_list': model_feature_list,
                            'model': clf,
                            'config_file': config_file,
                            'feature_file': todo['feature_file'],
                            'test_IDs': test_IDs,
                            'train_IDs': train_IDs,
                            'scaler': scaler
                        }
                        joblib.dump(model_output_dict,
                                    model_filename)

                    # if-elif that switches based on model type, end sklearn, start keras models
                    elif model_dict['model'] == 'flatwindow':
                        spects = feature_file['neuralnet_inputs']['flatwindow']

                        if 'flatwindow' not in locals():
                            from hvc.neuralnet.models import flatwindow

                        if 'convert_labels_categorical' not in locals():
                            from hvc.neuralnet.utils import convert_labels_categorical

                        if 'SpectScaler' not in locals():
                            from hvc.neuralnet.utils import SpectScaler

                        if 'labels_test_onehot' not in locals():
                            labels_test_onehot = \
                                convert_labels_categorical(feature_file['labelset'],
                                                           labels_test)

                        if 'test_spects' not in locals():
                            # get spects for test set,
                            # also add axis so correct input_shape for keras.conv_2d
                            test_spects = spects[test_IDs, :, :]

                        labels_train_onehot = \
                            convert_labels_categorical(feature_file['labelset'],
                                                       labels_train)

                        # get spects for train set,
                        # also add axis so correct input_shape for keras.conv_2d
                        train_spects = spects[train_IDs, :, :]

                        # scale all spects by mean and std of training set
                        spect_scaler = SpectScaler()
                        # concatenate all spects then rotate so
                        # Hz bins are columns, i.e., 'features'
                        spect_scaler.fit(train_spects)
                        train_spects_scaled = spect_scaler.transform(train_spects)
                        test_spects_scaled = spect_scaler.transform(test_spects)

                        # have to add 'channels' axis for keras 2-d convolution
                        # even though these are spectrograms, don't have channels
                        # like an image would.
                        # Decided to leave it explicit here instead of hiding in a function
                        train_spects_scaled = train_spects_scaled[:, :, :, np.newaxis]
                        test_spects_scaled = test_spects_scaled[:, :, :, np.newaxis]

                        num_samples, num_freqbins, num_timebins, num_channels = train_spects_scaled.shape
                        num_label_classes = len(feature_file['labelset'])
                        input_shape = (num_freqbins, num_timebins, num_channels)
                        flatwin = flatwindow(input_shape=input_shape,
                                             num_syllable_classes=num_label_classes)
                        import pdb;pdb.set_trace()
                        filename = bird_ID + '_' + 'flatwindow_training_' + now_str + \
                                   '.log'
                        csv_logger = CSVLogger(filename,
                                               separator=',',
                                               append=True)
                        weights_filename = bird_ID + '_' + "weights " + now_str + \
                                           ".best.hdf5"
                        checkpoint = ModelCheckpoint(weights_filename,
                                                     monitor='val_acc',
                                                     verbose=1,
                                                     save_best_only=True,
                                                     save_weights_only=True,
                                                     mode='max')
                        earlystop = EarlyStopping(monitor='val_acc',
                                                  min_delta=0,
                                                  patience=20,
                                                  verbose=1,
                                                  mode='auto')
                        callbacks_list = [csv_logger, checkpoint, earlystop]

                        flatwindow.fit(train_spects,
                                       train_labels,
                                       validation_data=(validat_spects, validat_labels),
                                       batch_size=model_dict['batch size'],
                                       nb_epoch=model_dict['epochs'],
                                       callbacks=callbacks_list,
                                       verbose=1)

                        pred_labels = flatwindow.predict_classes(test_spects_scaled,
                                                                 batch_size=32,
                                                                 verbose=1)

                        acc_by_label, avg_acc = hvc.utils.get_acc_by_label(test_syl_labels_zero_to_n,
                                                                           pred_labels,
                                                                           classes_zero_to_n)

        # after looping through all samples + replicates
        output_dict = {
            'config_file': config_file,
            'feature_file': todo['feature_file'],
            'num_train_samples_list': num_train_samples_list,
            'num_replicates': num_replicates,
            'model_dict': model_dict,
            'test_IDs': test_IDs,
            'train_IDs_arr': train_IDs_arr,
            'score_arr': score_arr,
            'avg_acc_arr': avg_acc_arr,
            'pred_labels_arr': pred_labels_arr,
        }
        joblib.dump(output_dict, output_filename)
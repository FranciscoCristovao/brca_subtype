import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split, StratifiedKFold
import matplotlib.pyplot as plt
from sklearn.preprocessing import OneHotEncoder
from tensorflow.keras.callbacks import EarlyStopping
from sklearn.metrics import confusion_matrix

import argparse

from vae import VAE


#####################
## Parse arguments ##
#####################

def get_params(param):
	params = parameter_df.loc[param, "value"]
	return params


parser = argparse.ArgumentParser(description="Get VAE arguments")
parser.add_argument("--parameter_file", "--p", help="Location of the file containing the parameters")
parser.add_argument("--hidden_dim", "--h", type=int, help="Dimension of hidden layer, 0 if none")
parser.add_argument("--latent_dim", "--l", type=int, help="Dimension of embedded layer, 0 if none")
parser.add_argument("--batch_size", "--b", type=int, help="Batch size for VAE train")
parser.add_argument("--epochs", "--e", type=int, help="Number of epochs for the VAE")
parser.add_argument("--learning_rate", "--l_rate", type=float, help="Learning rate for the VAE")
parser.add_argument("--dropout_input", "--d_in", type=float, help="Dropout rate of the input layer")
parser.add_argument("--dropout_hidden", "--d_hidden", type=float, help="Dropout rate of the hidden layers")
parser.add_argument("--dropout_decoder", "--d_decoder", type=bool, help="Flag for decoder dropout: 0 for dropout only on encoder, 1 otherwise")
parser.add_argument("--freeze_weights", "--freeze", type=bool, help="Flag that tells whether the Autoencoder weights are frozen or not when training the classifier")
parser.add_argument("--classifier_use_z", "--use_z", type=bool, help="Flag that tells whether the classifier feature space is a sampled z")
parser.add_argument("--reconstruction_loss", "--rec_loss", type=str, help="Autoencoder reconstruction loss: mse or binary_crossentropy")


args = parser.parse_args()

if args.parameter_file is not None:
	parameter_df = pd.read_csv(args.parameter_file, index_col=0)

	hidden_dim = int(get_params("hidden_dim"))
	latent_dim = int(get_params("latent_dim"))
	batch_size = int(get_params("batch_size"))
	epochs = int(get_params("epochs"))
	learning_rate = float(get_params("learning_rate"))
	dropout_input = float(get_params("dropout_input"))
	dropout_hidden = float(get_params("dropout_hidden"))
	dropout_decoder = True
	freeze_weights = False
	classifier_use_z = False
	reconstruction_loss = str(get_params("reconstruction_loss"))

else:

	hidden_dim = args.hidden_dim
	latent_dim = args.latent_dim
	batch_size = args.batch_size
	epochs = args.epochs
	learning_rate = args.learning_rate
	dropout_input = args.dropout_input
	dropout_hidden = args.dropout_hidden
	dropout_decoder = True
	freeze_weights = False
	classifier_use_z = False
	reconstruction_loss = args.reconstruction_loss


###############
## Load Data ##
###############

X_tcga = pd.read_pickle("../data/tcga_raw_no_labelled_brca_log_row_normalized.pkl")


#############################
## 5-Fold Cross Validation ##
#############################

confusion_matrixes = []
validation_set_percent = 0.1


dropout_input = 0.6
dropout_hidden = 0.6

random_gen = [10, 50, 23, 42, 4, 6, 43, 75, 22, 1]

data_percent = [0.25]

for percent in data_percent:
	
	X_brca_train_all = pd.read_pickle("../data/tcga_brca_raw_19036_row_log_norm_train.pkl")
	
	if percent<1:
		X_brca_train, trash = train_test_split(X_brca_train_all, train_size=percent, stratify=X_brca_train_all["Ciriello_subtype"], shuffle=True)
	else:
		X_brca_train = X_brca_train_all

	y_brca_train = X_brca_train["Ciriello_subtype"]
	X_brca_train.drop(['tcga_id', 'Ciriello_subtype', 'sample_id', 'cancer_type'], axis="columns", inplace=True)

	for s_index in range(10):

		skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=random_gen[s_index])
		scores = []
		i=1
		classify_df = pd.DataFrame(columns=["Fold", "accuracy"])

		for train_index, test_index in skf.split(X_brca_train, y_brca_train):
			print('Fold {} of {}'.format(i, skf.n_splits))

			X_train, X_val = X_brca_train.iloc[train_index], X_brca_train.iloc[test_index]
			y_train, y_val = y_brca_train.iloc[train_index], y_brca_train.iloc[test_index]

			# Prepare data to train Variational Autoencoder (merge dataframes and normalize)
			X_autoencoder = pd.concat([X_train, X_tcga], sort=True)
			scaler = MinMaxScaler()
			X_autoencoder_scaled = pd.DataFrame(scaler.fit_transform(X_autoencoder), columns=X_autoencoder.columns)

			# Scale logistic regression data
			X_train = pd.DataFrame(scaler.transform(X_train), columns=X_train.columns)
			X_val = pd.DataFrame(scaler.transform(X_val), columns=X_val.columns)

			#Split validation set
			X_autoencoder_val = X_autoencoder_scaled.sample(frac=validation_set_percent)
			X_autoencoder_train = X_autoencoder_scaled.drop(X_autoencoder_val.index)


			# Order the features correctly before training

			X_autoencoder_train = X_autoencoder_train.reindex(sorted(X_autoencoder_train.columns), axis="columns")
			X_autoencoder_val = X_autoencoder_val.reindex(sorted(X_autoencoder_val.columns), axis="columns")
			X_train = X_train.reindex(sorted(X_train.columns), axis="columns")
			X_val = X_val.reindex(sorted(X_val.columns), axis="columns")


			#Train the Model
			vae = VAE(original_dim=X_autoencoder_train.shape[1], 
					intermediate_dim=hidden_dim, 
					latent_dim=latent_dim, 
					epochs=epochs, 
					batch_size=batch_size, 
					learning_rate=learning_rate, 
					dropout_rate_input=dropout_input,
					dropout_rate_hidden=dropout_hidden,
					freeze_weights=freeze_weights, 
					classifier_use_z=classifier_use_z,
					rec_loss=reconstruction_loss)

			vae.initialize_model()
			vae.train_vae(train_df=X_autoencoder_train, val_df=X_autoencoder_val)

			# Build and train stacked classifier
			enc = OneHotEncoder(sparse=False)
			y_labels_train = enc.fit_transform(y_train.values.reshape(-1, 1))
			y_labels_val = pd.DataFrame(enc.fit_transform(y_val.values.reshape(-1, 1)))

			if(y_labels_val.shape[1]<5):
				y_labels_val = y_labels_val.assign(dummy=0.0)
			print(y_labels_val)

			X_train_train, X_train_val, y_labels_train_train, y_labels_train_val = train_test_split(X_train, y_labels_train, test_size=0.2, stratify=y_train, random_state=42)

			print("BUILDING CLASSIFIER")
			vae.build_classifier()

			fit_hist = vae.classifier.fit(x=X_train_train, 
										y=y_labels_train_train, 
										shuffle=True, 
										epochs=100,
										batch_size=50,
										callbacks=[EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)],
										validation_data=(X_train_val, y_labels_train_val))

			if(vae.classifier_use_z):
				X_val_new = pd.DataFrame(np.repeat(X_val.values, 10, axis=0))
				X_val_new.columns = X_val.columns
				y_labels_val_new = pd.DataFrame(np.repeat(y_labels_val.values, 10, axis=0))


				score = vae.classifier.evaluate(X_val_new, y_labels_val_new)
			else:
				score = vae.classifier.evaluate(X_val, y_labels_val)

			print(score)
			scores.append(score[1])

			classify_df = classify_df.append({"Fold":str(i), "accuracy":score[1]}, ignore_index=True)
			history_df = pd.DataFrame(fit_hist.history)

			i+=1

		print('5-Fold results: {}'.format(scores))
		print('Average accuracy: {}'.format(np.mean(scores)))


		classify_df = classify_df.assign(mean_accuracy=np.mean(scores))
		classify_df = classify_df.assign(intermediate_dim=hidden_dim)
		classify_df = classify_df.assign(latent_dim=latent_dim)
		classify_df = classify_df.assign(batch_size=batch_size)
		classify_df = classify_df.assign(epochs_vae=epochs)
		classify_df = classify_df.assign(learning_rate=learning_rate)
		classify_df = classify_df.assign(dropout_input=dropout_input)
		classify_df = classify_df.assign(dropout_hidden=dropout_hidden)
		classify_df = classify_df.assign(dropout_decoder=dropout_decoder)
		classify_df = classify_df.assign(freeze_weights=freeze_weights)
		classify_df = classify_df.assign(classifier_use_z=classifier_use_z)
		classify_df = classify_df.assign(classifier_loss="categorical_crossentropy")
		classify_df = classify_df.assign(reconstruction_loss=reconstruction_loss)

		output_filename="../results/performance_curves/VAE/tcga_{}_brca_data_split_{}_classifier.csv".format(percent, s_index)
		classify_df.to_csv(output_filename, sep=',')



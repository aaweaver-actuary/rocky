"""
This module contains the BaseEstimator class, which is the base class for all
models and estimators in the rocky package.
"""
# import Triangle
# try:
#     from ..triangle import Triangle
# except:
#     from triangle import Triangle
from triangle import Triangle

# import TriangleTimeSeriesSplit
# try:
#     from ..TriangleTimeSeriesSplit import TriangleTimeSeriesSplit
# except:
#     from TriangleTimeSeriesSplit import TriangleTimeSeriesSplit
from TriangleTimeSeriesSplit import TriangleTimeSeriesSplit

from dataclasses import dataclass
import numpy as np
import pandas as pd

from ModelPlot import Plot


@dataclass
class BaseEstimator:
    """
    Base model class.

    The methods in this class are used by all models and estimators in the
    rocky package. Those that are not implemented in this class must be
    implemented in the child class.

    All added models should inherit from this class, and should implement methods
    as needed.
    """

    id: str
    model_class: str = None
    model: object = None
    tri: Triangle = None
    exposure: pd.Series = None
    coef: np.ndarray[float] = None
    is_fitted: bool = False
    n_validation: int = 0
    weights: pd.Series = None
    cv: TriangleTimeSeriesSplit = None
    X_train: pd.DataFrame = None
    X_forecast: pd.DataFrame = None
    y_train: pd.Series = None
    use_cal: bool = False
    plot: Plot = None
    acc: pd.Series = None
    dev: pd.Series = None
    cal: pd.Series = None
    has_combined_params: bool = False
    acc_forecast: pd.Series = None
    dev_forecast: pd.Series = None
    cal_forecast: pd.Series = None
    must_be_positive: bool = False

    def __post_init__(self):
        # print(f"must be positive: {self.must_be_positive}")
        if self.weights is None:
            self.weights = np.ones(self.tri.tri.shape[0])

        # build idx
        self._build_idx()

        # initialize matrices
        self._initialize_matrices()

        # initialize the plotting object
        self.plot = Plot()

        # order the columns of X_train and X_forecast
        self.column_order = self.GetX("train").columns.tolist()

    def __repr__(self):
        return f"{self.__class__.__name__}({self.id})"

    def _build_idx1(self):
        # index where y is positive and observed
        is_positive = self.tri.positive_y
        is_observed = self.tri.X_base.loc[
            self.tri.X_base["is_observed"] == 1
        ].index.values
        total = self.tri.X_base.index.values
        is_forecast = np.setdiff1d(total, is_observed)
        return is_positive, is_observed, is_forecast

    def _build_idx(self):
        is_positive, is_observed, is_forecast = self._build_idx1()

        # depending on the model, we may want to drop non-positive y values
        # if so, set must_be_positive to True in the child class
        if self.must_be_positive:
            self.initial_train_idx = np.intersect1d(is_positive, is_observed)
        else:
            self.initial_train_idx = is_observed
        self.initial_forecast_idx = is_forecast

        self.train_index = self.initial_train_idx
        self.forecast_index = self.initial_forecast_idx

    def _initialize_matrices(self):
        # initialize X_train, X_forecast, and y_train
        self.X_train = self.GetXBase("train")
        self.X_forecast = self.GetXBase("forecast")
        self.y_train = self.GetYBase("train")

        # initialize the acc, dev, cal attributes (train set)
        self.acc = self.tri.get_X_id("train")["accident_period"]
        self.dev = self.tri.get_X_id("train")["development_period"]
        self.cal = self.tri.get_X_id("train")["calendar_period"]
        self.exposure = self.tri.get_X_id("train")["exposure"]

        # initialize forecasting attributes
        self.acc_forecast = self.tri.get_X_id("forecast")["accident_period"]
        self.dev_forecast = self.tri.get_X_id("forecast")["development_period"]
        self.cal_forecast = self.tri.get_X_id("forecast")["calendar_period"]
        self.exposure_forecast = self.tri.get_X_id("forecast")["exposure"]

    def combine_indices(self, *args):
        """
        Combine indices into a single index.

        Parameters
        ----------
        args : np.ndarray
            Indices to combine. If multiple indices are passed, they must each
            be an array. The indicies will be concatenated along the first axis
            to form a single index.

        Returns
        -------
        np.ndarray
            Combined index.
        """
        return (
            pd.Series(np.concatenate(args, axis=0))
            .drop_duplicates()
            .sort_values()
            .values
        )

    def __repr__(self):
        raise NotImplementedError

    def _update_attributes(self, after="fit", **kwargs):
        """
        Update the model's attributes after fitting.
        """
        raise NotImplementedError

    def _update_plot_attributes(self, **kwargs):
        """
        Update the model's attributes for plotting.
        """
        raise NotImplementedError

    def GetIdx(self, kind="train"):
        if kind == "train":
            idx = self.train_index
        elif kind == "forecast":
            idx = self.forecast_index
        elif kind == "all" or kind is None:
            idx = self.train_index.tolist() + self.forecast_index.tolist()
            idx = pd.Series(idx).sort_values().drop_duplicates().values
        else:
            raise ValueError("kind must be 'train', 'forecast', or 'all'")
        return idx

    def GetXBase(self, kind="train"):
        """
        This is a wrapper function for the Triangle class's get_X_base method.

        Returns the base triangle data for the model.
        """
        # get index
        idx = self.GetIdx(kind)

        # get X
        X = self.tri.get_X_base(kind, cal=self.use_cal)

        # filter X and return
        X = X.loc[idx, :]
        return X

    def GetYBase(self, kind="train"):
        """
        This is a wrapper function for the Triangle class's get_y_base method.

        Returns the base triangle data for the model.

        Parameters
        ----------
        """
        idx = self.GetIdx(kind)

        y = self.tri.get_y_base(kind)
        y = y[idx]
        return y
    
    def GetAcc(self, kind:str = None) -> pd.Series:
        """
        Getter for the model's accident period vector, filtered for the 
        current model context and kind.

        Parameters
        ----------
        kind : str, optional
            The type of data to return. If None, return all data. If "train",
            return only the training data. If "forecast", return only the
            forecast data. If "all", return both the training and forecast
            data. The default is None.

        Returns
        -------
        pd.Series
            The accident period vector.
        """
        # get current context index
        idx = self.GetIdx(kind)

        # get accident period vector
        if kind is None or kind == "all":
            acc = pd.concat([self.acc, self.acc_forecast])
        elif kind == "train":
            acc = self.acc
        elif kind == "forecast":
            acc = self.acc_forecast            
        else:
            raise ValueError("kind must be 'train', 'forecast', 'all'")

        # filter and return
        return acc[idx]
    
    def GetDev(self, kind:str = None) -> pd.Series:
        """
        Getter for the model's development period vector, filtered for the
        current model context and kind.

        Parameters
        ----------
        kind : str, optional
            The type of data to return. If None, return all data. If "train",
            return only the training data. If "forecast", return only the
            forecast data. If "all", return both the training and forecast
            data. The default is None.

        Returns
        -------
        pd.Series
            The development period vector.
        """
        # get current context index
        idx = self.GetIdx(kind)

        # get development period vector
        if kind is None or kind == "all":
            dev = pd.concat([self.dev, self.dev_forecast])
        elif kind == "train":
            dev = self.dev
        elif kind == "forecast":
            dev = self.dev_forecast            
        else:
            raise ValueError("kind must be 'train', 'forecast', 'all'")

        # filter and return
        return dev[idx]
    
    def GetCal(self, kind:str = None) -> pd.Series:
        """
        Getter for the model's calendar period vector, filtered for the
        current model context and kind.

        Parameters
        ----------
        kind : str, optional
            The type of data to return. If None, return all data. If "train",
            return only the training data. If "forecast", return only the
            forecast data. If "all", return both the training and forecast
            data. The default is None.

        Returns
        -------
        pd.Series
            The calendar period vector.
        """
        # get current context index
        idx = self.GetIdx(kind)

        # get calendar period vector
        if kind is None or kind == "all":
            cal = pd.concat([self.cal, self.cal_forecast])
        elif kind == "train":
            cal = self.cal
        elif kind == "forecast":
            cal = self.cal_forecast            
        else:
            raise ValueError("kind must be 'train', 'forecast', 'all'")

        # filter and return
        return cal[idx]
    
    def GetExposure(self, kind:str = None) -> pd.Series:
        """
        Getter for the model's exposure vector, filtered for the current model
        context and kind.

        Parameters
        ----------
        kind : str, optional
            The type of data to return. If None, return all data. If "train",
            return only the training data. If "forecast", return only the
            forecast data. If "all", return both the training and forecast
            data. The default is None.

        Returns
        -------
        pd.Series
            The exposure vector.
        """
        # get current context index
        idx = self.GetIdx(kind)

        # get exposure vector
        if kind is None or kind == "all":
            exposure = pd.concat([self.exposure, self.exposure_forecast])
        elif kind == "train":
            exposure = self.exposure
        elif kind == "forecast":
            exposure = self.exposure_forecast            
        else:
            raise ValueError("kind must be 'train', 'forecast', 'all'")

        # filter and return
        return exposure[idx]
        
        
    def GetX(self, kind=None):
        """
        Getter for the model's X data. If there is no X data, take the base design
        matrix directly from the triangle. When parameters are combined, X is
        created as the design matrix of the combined parameters.
        """
        idx = self.GetIdx(kind)

        if kind is None or kind == "all":
            df = pd.concat([self.X_train, self.X_forecast])
        elif kind == "train":
            df = self.X_train
        elif kind == "forecast":
            df = self.X_forecast
        else:
            raise ValueError("kind must be 'train', 'forecast', 'all'")

        def cond(x):
            return x != "intercept" and x != "is_observed"

        condition = ["intercept"]
        for c in df.columns:
            if cond(c):
                condition.append(c)

        df = df[condition]

        return df.loc[idx, :]

    def GetParameterNames(self, column=None):
        """
        Getter for the model's parameter names.
        """
        print("GetParameterNames is not implemented for this model.")
        raise NotImplementedError

    def GetY(self, kind:str = "train") -> pd.Series:
        """
        Getter for the model's y data. If there is no y data, take the y vector
        directly from the triangle.
        """
        # get index to filter y
        idx = self.GetIdx(kind)

        # get the correct version of y depending on the kind
        if kind.lower() in ["train", "forecast"]:
            if kind.lower() == "train":
                return self.y_train[idx]
            elif kind.lower() == "forecast":
                raise ValueError("y_forecast is what we are trying to predict!")
        else:
            raise ValueError("kind must be 'train' for `y`")
        
    def GetWeights(self, kind:str = "train") -> pd.Series:
        """
        Getter for the model's weights. If there are no weights, return None.
        """
        idx = self.GetIdx(kind)
        if kind.lower() == "train":
            return self.weights[idx]
        else:
            raise ValueError("kind must be 'train' for `weights`")

    def GetN(self) -> int:
        """
        Getter for the model's number of observations. 
        
        This is equal to the number of rows in the "train"
        design matrix.

        Returns
        -------
        int
            Number of observations.
        """
        return self.GetX("train").shape[0]

    def GetP(self) -> int:
        """
        Getter for the model's number of parameters.

        This is equal to the number of columns in the "train"
        design matrix, excluding those that have no nonzero 
        values in the design matrix.

        Must do this because if there are calendar year parameters,
        about half of them will be unobserved and thus have no
        nonzero values in the design matrix. They are not parameters
        in the normal sense, so we exclude them from the count.

        Returns
        -------
        int
            Number of parameters.
        """
        # p, unadjusted for columns that are completely 0
        unadj_p = self.GetX("train").shape[1]

        # p, adjusted for columns that are completely 0
        adj_p = unadj_p - self.GetX("train").isna().all().sum()
        
        return adj_p

    def GetDegreesOfFreedom(self) -> int:
        """
        Getter for the model's degrees of freedom.

        Degrees of freedom is equal to the number of observations
        minus the number of parameters.

        Returns
        -------
        int
            Degrees of freedom.
        """
        return self.GetN() - self.GetP()

    def GetVarY(self, kind="train"):
        """

        """
        print("VarY is not implemented for this model.")
        raise NotImplementedError

    def Fit(
        self,
        X: pd.DataFrame = None,
        y: pd.Series = None,
        **kwargs,
    ) -> None:
        print("Fit is not implemented for this model.")
        raise NotImplementedError

    def ManualFit(self, **kwargs):
        print("ManualFit is not implemented for this model.")
        raise NotImplementedError

    def Predict(self, kind: str = None, X: pd.DataFrame = None) -> pd.Series:
        print("Predict is not implemented for this model.")
        raise NotImplementedError

    def Ultimate(self, tail=None) -> pd.Series:
        X = self.GetX(kind="forecast", )
        df = pd.DataFrame(
            {
                "Accident Period": self.tri.get_X_id("all").accident_period,
                f"{self.model_name} Ultimate": self.GetY(kind="train").tolist()
                + self.Predict("forecast", X).tolist(),
            }
        )

        df = df.groupby("Accident Period").sum()[f"{self.model_name} Ultimate"].round(0)

        if tail is None:
            tail = 1
        df = df * tail

        df.index = self.tri.tri.index
        return df

    def GetYhat(self, kind: str = None) -> pd.Series:
        return self.Predict(kind=kind)

    def GetParameters(self) -> pd.DataFrame:
        """
        Get the parameters of the model.

        Returns
        -------
        pd.DataFrame
            The parameters of the model.
        """
        print("GetParameters is not implemented for this model.")
        raise NotImplementedError

    def PredictTriangle(self):
        yhat = pd.DataFrame(dict(yhat=self.Predict()))
        _ids = self.tri.get_X_id()
        return pd.concat([_ids, yhat], axis=1)

    def GetSaturatedModel(self):
        raise NotImplementedError

    def LogPi(self):
        cls_name = self.__class__.__name__
        print("LogPi not implemented for this model")
        print(f"They must be specifically implemented in the {cls_name} class")
        raise NotImplementedError

    def LogLikelihood(self):
        return np.sum(self.LogPi())

    def Deviance(self):
        """
        D(Y, Y_hat) = 2 * sum(Y * log(Y / Y_hat) - (Y - Y_hat))
                    = 2 * sum[loglik(saturated model) - loglik(fitted model)]
        """
        print("Deviance not implemented for this model")
        raise NotImplementedError

    def RawResiduals(self):
        return self.GetY() - self.GetYhat()

    def PearsonResiduals(self):
        res = np.divide(self.RawResiduals(), np.sqrt(self.VarY()))
        return res

    def DevianceResiduals(self):
        """
        Deviance residuals are defined as:
        R_i^D = sign(Y_i - Y_hat_i) *
                sqrt(2 * [Y_i * log(Y_i / Y_hat_i) - (Y_i - Y_hat_i)])
        """
        print("DevianceResiduals not implemented for this model")
        raise NotImplementedError

    def ScaleParameter(self):
        print("ScaleParameter not implemented for this model")
        raise NotImplementedError

    def GetYearTypeDict(self):
        d = {
            "accident": "acc",
            "acc": "acc",
            "ay": "acc",
            "accident_year": "acc",
            "development": "dev",
            "dy": "dev",
            "dev": "dev",
            "development_year": "dev",
            "development_period": "dev",
            "calendar": "cal",
            "cal": "cal",
            "cy": "cal",
            "calendar_year": "cal",
        }
        return d

    def Combine(
        self, year_type: str, year_list: list, combined_name: str = None
    ) -> pd.DataFrame:
        """
        This function combines parameters of the design matrix to have the same value.

        THIS SHOULD JUST BE A MAPPING BETWEEN ORIGINAL "BASE" PARAMETERS AND COMBINED
        PARAMETERS SO THE BASE SET CAN BE USED FOR ORDERING, ETC, AND KEEPING AY
        PARAMETERS TOGETHER, DEV PARAM TOGETHER, ETC
        """
        # run through recode year-type dictionary
        year_type = self.GetYearTypeDict()[year_type.lower()]

        # check that acceptable year_type was passed
        if year_type not in ["acc", "dev", "cal"]:
            raise ValueError("Year type must be 'acc', 'dev', or 'cal'")

        # make a copy of the current design matrix
        X_train = self.GetX("train").copy()
        X_forecast = self.GetX("forecast").copy()
        X_new_train = X_train.copy()
        X_new_forecast = X_forecast.copy()

        # recode combined name
        if combined_name is None:
            combined_name = f"{year_type}_combined"
        combined_param_name = combined_name.lower().replace(" ", "_").replace(".", "_")

        if year_type == "acc":
            # generate column names
            cols_to_combine = ["accident_period_" + str(year) for year in year_list]

            # check if columns exist in the DataFrame
            if not set(cols_to_combine).issubset(X_train.columns):
                raise ValueError(
                    "One or more columns specified do not exist in the DataFrame"
                )

            # add new column that is the sum of the specified accident year columns
            X_new_train[combined_param_name] = X_new_train[cols_to_combine].sum(axis=1)
            X_new_forecast[combined_param_name] = X_new_forecast[cols_to_combine].sum(
                axis=1
            )

            # drop the original columns
            X_new_train = X_new_train.drop(columns=cols_to_combine)
            X_new_forecast = X_new_forecast.drop(columns=cols_to_combine)

        elif year_type == "dev":
            # generate column names
            cols_to_combine = [
                "development_period_" + pd.Series([year]).astype(str).str.zfill(4)[0]
                for year in year_list
            ]

            # check if columns exist in the DataFrame
            # if not set(cols_to_combine).issubset(X_train.columns.tolist()):
            for col in cols_to_combine:
                print(col)
                assert col in X_train.columns.tolist(), f"{col} not in X_train.columns"

            # add new column that is the sum of the specified development year columns
            X_new_train[combined_param_name] = X_new_train[cols_to_combine].sum(axis=1)
            X_new_forecast[combined_param_name] = X_new_forecast[cols_to_combine].sum(
                axis=1
            )

            # drop the original columns
            X_new_train = X_new_train.drop(columns=cols_to_combine)
            X_new_forecast = X_new_forecast.drop(columns=cols_to_combine)

        # reset X_train, X_forecast
        self.X_train = X_new_train
        self.X_forecast = X_new_forecast

        self.has_combined_params = True

        # refit the model
        self.Fit()

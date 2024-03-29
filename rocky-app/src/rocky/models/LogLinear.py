# rocky code
from rocky.triangle import Triangle
from rocky.model_selection.TriangleTimeSeriesSplit import TriangleTimeSeriesSplit
from rocky.plot.ModelPlot import Plot
from rocky.models.BaseEstimator import BaseEstimator

# for class attributes/definitions
from dataclasses import dataclass

# for fitting the model
from sklearn.linear_model import LinearRegression, Ridge, Lasso, ElasticNet

# hetero adjustment
from sklearn.cluster import KMeans, AgglomerativeClustering
from sklearn.metrics import mean_squared_error

# for plotting
import plotly.express as px
import plotly.subplots as sp
import plotly.graph_objs as go

# for warnings
import warnings

# for working with data
import numpy as np
import pandas as pd
pd.options.plotting.backend = "plotly"


@dataclass
class LogLinear(BaseEstimator):
    """
    Loglinear class. For compatability and testing only. Please exercise caution when
    using these estimates, and ensure that you have a good understanding of the
    underlying model and require it before using these estimates in production,
    particularly when selecting carried reserves.

    Model
    -----
    i = accident period
    j = development period
    k = i + j = calendar period
    
    beta = parameter vector
    X = design matrix
    y = response vector

    alpha = accident period level
    gamma = development period trend (log scale)
    iota = calendar period trend (log scale)

    E[y_i] = exp(X_{i} * beta)

    E[beta_{i,j}] = alpha_i + sum_{m=1}^{j} gamma_m + sum_{n=1}^{i+j} iota_n
    """

    id: str
    model_class: str = None
    model: object = None
    tri: Triangle = None
    standardize: bool = True # whether or not to standardize the data behind the scenes
    intercept: float = None
    coef: np.ndarray[float] = None
    is_fitted: bool = False
    n_validation: int = 0
    saturated_model = None
    hetero_clusters: pd.Series = None
    weights: pd.Series = None
    distribution_family: str = None
    alpha: float = None
    l1_ratio: float = None
    max_iter: int = 100000
    link: str = "log"
    cv: TriangleTimeSeriesSplit = None
    X_train: pd.DataFrame = None
    X_forecast: pd.DataFrame = None
    y_train: pd.Series = None
    use_cal: bool = False
    plot: Plot = None
    acc: pd.Series = None
    dev: pd.Series = None
    cal: pd.Series = None
    must_be_positive: bool = True
    model_name: str = "Log-linear"

    def __post_init__(self):
        super().__post_init__()
        print(
            "This is for testing and compatability only. \
Please do not assign much credibility to these estimates for the purposes \
selecting carried reserves."
        )
        self.hetero_adjustment = pd.Series(np.ones_like(self.GetDev('train')),
                                           index=self.GetIdx('train'))
        self.dy_w_gp = pd.Series(np.zeros_like(self.dev))
        # idx = self.GetX("train").columns.to_series()

        # turn development period into dummy variables for the base hetero
        # adjustment
        self.hetero_gp = pd.get_dummies(self.tri
                                        .get_X_id()['development_period']
                                        .astype(str)
                                        .str.zfill(3))
        self.hetero_gp = pd.concat([self.tri.get_X_id()['development_period'],
                                    self.hetero_gp], axis=1)
        for c in self.hetero_gp.columns.tolist():
            self.hetero_gp.rename(columns={c: f"hetero_{c}"}, inplace=True)
        self.hetero_gp.rename(
            columns={"hetero_development_period": "development_period"},
            inplace=True)
        self.hetero_weights = pd.Series(np.ones_like(self.dev))

        self.standardize_mu = None
        self.standardize_sigma = None
        

    def __repr__(self):
        if self.alpha is None:
            a = ""
        else:
            a = f"alpha={self.alpha:.1f}"

        if self.l1_ratio is None:
            p = ""
        else:
            if self.alpha is None:
                p = f"l1_ratio={self.l1_ratio:.2f}"
            else:
                p = f", l1_ratio={self.l1_ratio:.2f}"
        return f"loglinear({a}{p})"

    def _update_attributes(self, after="fit", **kwargs):
        """
        Update the model's attributes after fitting.
        """
        if after.lower() == "fit":
            self.intercept = self.model.intercept_
            self.coef = self.model.coef_
            self.is_fitted = True
        elif after.lower() == "x":
            self.X_train = kwargs.get("X_train", None)
            self.X_forecast = kwargs.get("X_forecast", None)

    def _update_plot_attributes(self, **kwargs):
        """
        Update the model's attributes for plotting.
        """
        if self.plot is not None:
            for arg in kwargs:
                setattr(self.plot, arg, kwargs[arg])
        else:
            raise AttributeError(f"{self.id} model object has no plot attribute.")


    def GetHeteroGp(self):
        # Development year groupings are the same as the development years
        # themselves, available in the design matrix
        df = self.hetero_gp
        cols = df.columns.to_series()

        # Get the development year columns
        cols = cols[cols.str.contains("dev")]
        
        
        df = df[cols]
        
        return df
    
    def GetWeights(self, kind="train"):
        """
        Get the weights for the model.
        """
        # get the hetero weights
        init = pd.DataFrame({
            'development_period': self.GetDev('train')},
            index=self.GetIdx(kind=kind))
        init['adj'] = self.hetero_weights if self.hetero_weights is not None else 1
        init['adj'] = init['adj'].fillna(1)

        # unique development periods (making a lookup table)
        dev_periods = init.copy().drop_duplicates().reset_index(drop=True)

        # get the hetero weights for the "kind" data
        df = (pd.DataFrame({"development_period":self.GetDev(kind=kind)})
             .merge(dev_periods,
             on='development_period',
             how='left')).fillna(1)
        
        # return the hetero adjustment as a series, with index
        # corresponding to the index of the "kind" data
        s = pd.Series(df['adj'].values, index=self.GetIdx(kind=kind))
        return s#, dev_periods, df
    
    def SetHyperparameters(self, alpha, l1_ratio, max_iter=100000):
        self.alpha = alpha
        self.l1_ratio = l1_ratio
        self.max_iter = max_iter

    def TuneFitHyperparameters(
        self,
        n_splits=5,
        param_grid=None,
        measures=None,
        tie_criterion="ave_mse_test",
        model_type="loglinear",
        **kwargs,
    ):
        # set the parameter grid to default if none is provided
        if param_grid is None:
            param_grid = {
                "alpha": np.arange(0, 3.1, 0.1),
                "l1_ratio": np.arange(0, 1.05, 0.025),
                "max_iter": [100000],
            }

        # if kwargs for alpha, p and max_iter are provided, use those
        if "alpha" in kwargs:
            param_grid["alpha"] = kwargs["alpha"]
        if "l1_ratio" in kwargs:
            param_grid["l1_ratio"] = kwargs["l1_ratio"]
        if "max_iter" in kwargs:
            param_grid["max_iter"] = kwargs["max_iter"]

        # set the cross-validation object
        cv = TriangleTimeSeriesSplit(
            self.tri,
            n_splits=n_splits,
            loglinear_grid=param_grid,
            model_type=model_type,
            model=self,
            X=self.GetX('train'),
            y=self.GetY('train'),
        )

        # set the parameter search grid
        cv.SetParameterGrid(alpha=param_grid["alpha"],
                            l1_ratio=param_grid["l1_ratio"],
                            max_iter=param_grid["max_iter"])

        # grid search & return the optimal model
        optimal_model = cv.OptimalParameters(measures=measures,
                                             tie_criterion=tie_criterion)

        # set the optimal hyperparameters
        self.alpha = optimal_model.alpha
        self.l1_ratio = optimal_model.l1_ratio

        # save cv object
        self.cv = cv

        # fit the model
        self.Fit()

    def GetZScoreParams(self, log=True):
        self.standardize_mu = self.GetYBase('train', log=log).mean()
        self.standardize_sigma = self.GetYBase('train', log=log).std()
    
    def GetY(self,
             kind:str = "train",
             log:bool = True,
             actual_scale:bool = False
            ) -> pd.Series:
        """
        Getter for the model's y data. If there is no y data, take the y vector
        directly from the triangle.
        """
        idx = self.GetIdx(kind)

        if kind.lower() in ["train", "forecast"]:
            if kind.lower() == "train":
                out = self.y_train[idx]
            elif kind.lower() == "forecast":
                raise ValueError("y_forecast is what we are trying to predict!")
        else:
            raise ValueError("kind must be 'train' for `y`")

        # adjust y by the weights
        out = out * self.GetWeights(kind=kind)
        
        if log:
            out = np.log(out)

        # standardize y if self.standardized is True
        if self.standardize and not actual_scale:
            if self.standardize_mu is None:
                self.GetZScoreParams(log=log)

            out = (out - self.standardize_mu) / self.standardize_sigma
        elif actual_scale:
            if self.standardize_mu is None:
                self.GetZScoreParams(log=log)
            out = out * self.standardize_sigma + self.standardize_mu
        return pd.Series(out, index=idx)

    def GetYhat(self,
                kind:str = "train",
                log:bool = True,
                actual_scale:bool = False):
        """
        Getter for the model's yhat data. Yhat is calculated from the fitted model.
        """

        if kind.lower() in ["train", "forecast"]:
            if kind.lower() == "train":
                out = self.Predict(X=self.GetX(kind="train"))
            elif kind.lower() == "forecast":
                out = self.Predict(X=self.GetX(kind="forecast"))
        else:
            raise ValueError("kind must be 'train' or 'forecast' for `yhat`")

        if actual_scale:
            out = out * self.standardize_sigma + self.standardize_mu

        if log:
            pass
        else:
            out = np.exp(out)
        out.index = self.GetIdx(kind)
        return out
        
    def GetParameters(self, parameter_type:str=None):
        """
        Getter for the model's parameters. If the parameters are taken directly from
        the current model object.
        """
        p = self.lookup_col(parameter_type)
        if p=='a':
            p1 = 'accident'
        elif p=='d':
            p1 = 'development'
        elif p=='c':
            p1 = 'calendar'
        elif p is None:
            p1 = None
        else:
            raise ValueError("parameter_type must be one of 'a', 'd', 'c'")
        

        coef = self.model.coef_
        names = self.model.feature_names_in_
        df = pd.DataFrame({"names": names, "param": coef})
        df['param_type'] = df.names.apply(lambda x: x.split('_')[0])

        if p1 is not None:
            assert p1 in list(df.param_type.unique()) + ['calendar'], \
            f"parameter_type ({p1}) must be one of {df.param_type.unique()}"
            df = df.loc[df.param_type.eq(p1)]

        return df

    def BasicHeteroAdjustment(self) -> pd.Series:
        """
        This function calculates a heteroskedasticity adjustment for each unique
        development period in the provided data, effectively handling the variance
        of residuals for each period.

        For each period, the function computes a heteroskedasticity adjustment based
        on the variance of residuals and the variance of residuals for the given
        period. If there is no data to make the adjustment, the function will fill
        missing values with the average of surrounding two weights.

        The function also creates an adjusted residuals column in the dataset by
        multiplying residuals with their corresponding heteroskedasticity adjustments. 
        
        Finally, the function updates the instance's 'hetero_adjustment' and 'weights'
        attributes with the newly calculated heteroskedasticity adjustments.

        Returns
        -------
        pd.Series
            The heteroskedasticity adjustments.
        """
        df = pd.concat([self.GetDev('train'),
                        pd.get_dummies(self.GetDev('train').astype(str).str.zfill(3),
                                    prefix='dev').astype(int)],
                                    axis=1)
        df['resid'] = self.GetY('train', log=True) - self.GetYhat('train', log=True)
        df['var_resid'] = df.resid.var()
        dev = self.GetDev('train')
        max_dev = dev.max()
        
        # Create an empty series to hold the adjustments
        adjustments = pd.Series(index=df.index)

        # Calculate a unique adjustment for each development period
        for period in df['development_period'].unique():
            period_data = df[df['development_period'] == period]
            var_dev = period_data.resid.var()
            if var_dev:
                hetero_adjustment = df['var_resid'] / var_dev
            else:
                hetero_adjustment = 1
            adjustments.loc[period_data.index] = hetero_adjustment

        # Replace null values with the average of surrounding two weights
        adjustments = adjustments.fillna(adjustments.rolling(2, min_periods=1).mean())

        # if dev period is greater than or equal to max dev period, set to 1
        adjustments.loc[adjustments.index.to_series().ge(max_dev)] = 1

        df['hetero_adjustment'] = adjustments
        df['adjusted_resid'] = df['resid'] * df['hetero_adjustment']
        df.drop(columns=['var_resid'], inplace=True)

        # # re-base the weights to be relative to the first development period
        # df['weights'] = df['hetero_adjustment'] / df['hetero_adjustment'].iloc[0]

        # Update the instance's attributes
        self.hetero_adjustment = df['hetero_adjustment']
        self.weights = df['hetero_adjustment']
        
        return df['hetero_adjustment']

    def FitHetero(self,
                  hetero_func: callable = BasicHeteroAdjustment,
                  stop_threshold: float = 0.01,
                  max_iterations: int = 10000
                  ):
        """
        Fit model with heteroskedasticity adjustment. Alternate between fitting the
        model and recalculating the heteroskedasticity adjustment, until the RMSE
        between successive heteroskedasticity adjustments is less than the
        `stop_threshold` or `max_iterations` is reached.
        
        Parameters
        ----------
        hetero_func: function, optional
            The function to compute the heteroskedasticity adjustment. 
            Defaults to `BasicHeteroAdjustment` method of the class.
        stop_threshold: float, optional
            The threshold for RMSE between successive heteroskedasticity adjustments. 
            If the RMSE is less than this value, the fitting process will stop. Defaults
            to 0.01.
        max_iterations: int, optional
            The maximum number of iterations for the fitting process. Defaults to 100.

        Returns
        -------
        None
        """
        prev_adjustment = None
        print("Fitting hetero adjustment: (Step/RMSE/L2-Norm)")
        for i, _ in enumerate(range(max_iterations)):
            # Fit the model
            self.Fit()
            # Compute heteroskedasticity adjustment
            adjustment = hetero_func(self)
            # Check stopping criterion
            if prev_adjustment is not None:
                rmse = np.sqrt(mean_squared_error(prev_adjustment,adjustment))
                print(f"{i}/{rmse:.4f}", end=' ')
                if rmse < stop_threshold:
                    break
            prev_adjustment = adjustment.copy()
        # Update the 'weights' attribute with the final adjustment
        self.weights = adjustment
        self.hetero_adjustment = adjustment
        self.weights.index = self.GetIdx('train')
        self.hetero_adjustment.index = self.GetIdx('train')
        
        # one final fit
        self.Fit()

    def fit_ward_clustering(self, n_clusters=None):
        if n_clusters is None:
            n_clusters = int(self.tri.n_dev / 2) + 1

        # compute residuals
        residuals = self.GetY('train') - self.GetYhat('train')

        # create design matrix for development periods
        X = pd.get_dummies(self.GetDev('train')
                            .astype(str)
                            .str.zfill(3),
                            prefix='dev').astype(int)
        X['residuals'] = residuals
        
        # Ward clustering model
        ward = AgglomerativeClustering(n_clusters=n_clusters,
                                       linkage='ward')
        
        # Fit model to residuals grouped by dev period level
        ward.fit(residuals.to_frame().merge(X,
                                            left_index=True,
                                            right_index=True))
        

        return ward

    def Fit(
        self,
        X: pd.DataFrame = None,
        y: pd.Series = None,
        alpha: float = None,
        l1_ratio: float = None,
        max_iter: int = None,
        n_splits=5,
        param_grid=None,
        measures=None,
        tie_criterion="ave_mse_test",
        **kwargs,
    ) -> None:
        """
        Fit the model to the Triangle data.

        Parameters
        ----------
        X : pd.DataFrame, optional
            The design matrix, by default None, which will use the design matrix
            from the Triangle object.
        y : pd.Series, optional
            The response vector, by default None, which will use the response
            vector from the Triangle object.
        alpha : float, optional
            The alpha hyperparameter, by default None, which will use the
            alpha from the glm object. If there is no alpha hyperparameter
            set, then a Pareto-optimal set of hyperparameters will be found
            using `TuneFitHyperparameters()`.
        power : float, optional
            The p hyperparameter, by default None, which will use the
            p from the glm object. If there is no p hyperparameter
            set, then a Pareto-optimal set of hyperparameters will be found
            using `TuneFitHyperparameters()`.
        max_iter : int, optional
            The maximum number of iterations, by default None, which will use
            the maximum number of iterations from the glm object. If there is
            no maximum number of iterations set, it will default to 100000.
        **kwargs
            Additional keyword arguments to pass to the glm object. See
            `sklearn.linear_model.ElasticNet` for more details.

        Returns
        -------
        None
            The model is fit in place.

        Notes
        -----
        If the hyperparameters are not set, then a Pareto-optimal set of
        hyperparameters will be found using `TuneFitHyperparameters()`.

        Examples
        --------
        >>> from rockycore import ROCKY
        >>> # create a ROCKY object
        >>> rky = ROCKY()
        >>> # load a triangle from the clipboard
        >>> rky.FromClipboard()
        >>> # add a GLM to `rky`
        >>> rky.AddModel()

        """
        # get X, y if not provided
        if X is None:
            X = self.GetX("train")

        if y is None:
            y = self.GetY("train", log=True)

        # if alpha or p are not provided, calculate the optimal values
        if alpha is None or l1_ratio is None:
            if self.alpha is None or self.l1_ratio is None:
                if self.alpha is None:
                    message = "`alpha`"
                    if self.l1_ratio is None:
                        message += " and `l1_ratio`"
                else:
                    message = "`l1_ratio`"
                    message += " is/are not set. Running `TuneFitHyperparameters()`..."

                warnings.warn(message)
                self.TuneFitHyperparameters(
                    n_splits=n_splits,
                    param_grid=param_grid,
                    measures=measures,
                    tie_criterion=tie_criterion,
                    model_type="loglinear",
                    model=self,
                )

        # now either alpha and l1_ratio are set or they were provided to begin with
        alpha = self.alpha if alpha is None else alpha
        l1_ratio = self.l1_ratio if l1_ratio is None else l1_ratio
        max_iter = self.max_iter if max_iter is None else max_iter

        # model object - if alpha is 0, then it is just a linear model
        if alpha == 0:
            self.model = LinearRegression(fit_intercept=False)
        else:
            # if l1_ratio is 1, then it is just a lasso model
            if l1_ratio == 1:
                self.model = Lasso(alpha=alpha, max_iter=max_iter, fit_intercept=False)
            # if l1_ratio is 0, then it is just a ridge model
            elif l1_ratio == 0:
                self.model = Ridge(alpha=alpha, max_iter=max_iter, fit_intercept=False)
            # otherwise, it is an elastic net model
            else:
                self.model = ElasticNet(alpha=alpha,
                                        l1_ratio=l1_ratio,
                                        max_iter=max_iter,
                                        fit_intercept=False)

        # make sure X does not have the `is_observed` column
        if "is_observed" in X.columns.tolist():
            X = X.drop(columns=["is_observed"])

        # fit the model
        self.model.fit(X, y)

        # update attributes
        self._update_attributes("fit")

        # add a plot object to the glm object now that it has been fit
        self.plot = Plot()
        self._update_plot_attributes(
            X_train=self.GetX("train"),
            y_train=self.GetY("train"),
            X_forecast=self.GetX("forecast"),
            X_id=self.tri.get_X_id("train"),
            yhat=self.GetYhat("train"),
            acc=self.acc,
            dev=self.dev,
            cal=self.cal,
            fitted_model=self,
        )

    def ManualFit(self, **kwargs):
        """
        Manually fit the model using provided coefficients. This is useful when
        you want to set the coefficients of the model manually instead of
        fitting the model using the data.

        Parameters
        ----------
        **kwargs
            Keyword arguments corresponding to the names of the coefficients in
            the design matrix and their respective values. For example, if you
            want to set the coefficient 'a' to 0.5, you would pass `a=0.5`.

        Returns
        -------
        None
            The model coefficients are updated in place.

        Notes
        -----
        This does not validate that the provided coefficients will result in a
        good fit to the data. It simply sets the coefficients to the provided
        values.

        Examples
        --------
        >>> rky = ROCKY()
        >>> rky.FromClipboard()
        >>> rky.AddModel('glm', 'glm')
        >>> rky.ManualFit(calendar_period_001=0.5, calendar_period_002=0.5)

        """
        # parameters
        params = self.GetParameters()

        # loop through the kwargs and set the coefficients of the model
        for key, value in kwargs.items():
            # get index of the key from the design matrix
            idx = params[params["parameter"] == key].index[0]

            # set the coefficient
            self.model.coef_[idx] = value

        # update attributes
        self._update_attributes("fit")
        self._update_plot_attributes(
            X_id=self.tri.get_X_id("train"),
            yhat=self.GetYhat("train"),
            acc=self.acc,
            dev=self.dev,
            cal=self.cal,
            fitted_model=self,
        )

    def Predict(self, kind: str = None, X: pd.DataFrame = None) -> pd.Series:
        if self.model is None:
            raise ValueError("Model has not been fit")

        if X is None:
            X = self.GetX(kind=kind)

        # drop the `is_observed` column if it exists
        if "is_observed" in X.columns.tolist():
            X = X.drop(columns=["is_observed"])

        yhat = self.model.predict(X)
        return pd.Series(yhat)
    
    def RawResiduals(self,
                     log:bool = True,
                     actual_scale:bool = False
                    ) -> pd.Series:
        """
        Get the raw residuals of the model.
        """
        out = self.GetY("train", log=log, actual_scale=actual_scale) 
        out -= self.GetYhat("train", log=log, actual_scale=actual_scale)
        return out.dropna()

    ###################################################################################
    ### In the next section, I reproduce the code from Josh Brady's ###################
    ### original rocky code. I am keeping the original methods and  ###################
    ### names, with the following exceptions:                       ###################
    ###   1. all methods get an underscore in front of their name   ###################
    ###   2. periods are replaced with underscores as well (not     ###################
    ###      allowed in python variable names                       ###################
    ###################################################################################

    # # copy table to clipboard
    # copy.table <- function(obj, size = ROCKY.settings$data$ClipboardSize,
    #                        row.names = FALSE, col.names = TRUE) {
    # clip <- paste('clipboard-', size, sep = '')
    # f <- file(description = clip, open = 'w')
    # write.table(obj, f, row.names = row.names, col.names = col.names, sep = '\t')
    # close(f)
    # }
    def _copy_table(
        self, df: pd.DataFrame = None, row_names: bool = False, col_names: bool = True
    ) -> None:
        """
        Copy table to clipboard.

        Parameters
        ----------
        df : pd.DataFrame, optional
            The table to copy to the clipboard, by default None, which will
            copy the table from the `tri` attribute.
        row_names : bool, optional
            Whether to include row names, by default False
        col_names : bool, optional
            Whether to include column names, by default True

        Returns
        -------
        None
            The table is copied to the clipboard.
        """
        if df is None:
            df = self.tri.tri

        df.to_clipboard(index=row_names, header=col_names)

    # # Paste data into R
    # paste.table <- function(header = TRUE) {
    # f <- file(description = 'clipboard', open = 'r')
    # df <- read.table(f, sep = '\t', header = header)
    # close(f)
    # return(df)
    # }
    def _paste_table(self, header: bool = True) -> pd.DataFrame:
        """
        Paste data from the clipboard.

        Parameters
        ----------
        header : bool, optional
            Whether the table has a header, by default True

        Returns
        -------
        pd.DataFrame
            The table from the clipboard.
        """
        df = pd.read_clipboard(header=header)
        return df

    # lagFnc <- function(vec,nlag = 1){
    # # creates a lagged vector lagged by nlag
    # l = length(vec)
    # return(c(rep(NA,nlag),vec[1:(l-nlag)]))
    # }
    def _lagFnc(self, vec: pd.Series, nlag: int = 1) -> pd.Series:
        """
        Creates a lagged vector lagged by nlag.

        Parameters
        ----------
        vec : pd.Series
            The vector to lag.
        nlag : int, optional
            The number of lags, by default 1

        Returns
        -------
        pd.Series
            The lagged vector.
        """
        return vec.shift(nlag)

    # # Population Variance -----------------------------------------------------
    # popVar <- function(y){
    # y <- y[!is.na(y)]
    # return(sum((y - mean(y))^2)/length(y))
    # }
    def _popVar(self, y: pd.Series) -> float:
        """
        Population variance.

        Parameters
        ----------
        y : pd.Series
            The vector to calculate the variance of.

        Returns
        -------
        float
            The population variance.
        """
        return np.sum((y - np.mean(y)) ** 2) / len(y)

    # ## 1.Function to input data and transfer to matrix table #########################
    # tritomatrix <- function(Triangle, beginAY = NA, beginCY = NA){
    # # This function take the input triangle and converts it to the long format
    #   suitable for modeling

    # # beginAY holds the minimum AY to keep

    # # Keep AYs >= beginAY
    # if (!is.na(beginAY)){
    #     Triangle <- Triangle[Triangle$AY >= beginAY,]
    # }

    # I <- dim(Triangle)[1]           # number of accident years
    # D1 <- dim(Triangle)[2] - 1       # number of development years + 1, gives column number for last AY

    # initay<- min(Triangle[,1])      # The first accident year
    # curray<- max(Triangle[,1])      # The current year

    # # adj for exposure, remove AY and Exposure columns
    # # sweep takes the triangle and divides '/' by the exposure vector accross rows
    # TriAdj = sweep(x = Triangle[,c(2:D1)],MARGIN = 1,STATS = Triangle[,dim(Triangle)[2]],FUN = '/')

    # D <- dim(TriAdj)[2]            # number of development year

    # TriAdj <-as.matrix(TriAdj)
    # dimnames(TriAdj)=list(AY=initay:curray, DY=0:(D-1))  # data is ready as input triangle

    # # convert to data frame
    # mymatx <- data.frame(
    #     AY=rep(initay:curray, D),
    #     DY=rep(0:(D-1), each=I),
    #     value=as.vector(TriAdj))

    # # If incremental<=0 set NA
    # mymatx$value[mymatx$value<=0] <- NA

    # # Add dimensions as factors
    # mydat <- with(mymatx, data.frame(AY, DY, CY=AY+DY,
    #                                 AYf=factor(AY),
    #                                 DYf=as.factor(DY),
    #                                 CYf=as.factor(AY+DY),value,
    #                                 logvalue=log(value)))

    # rownames(mydat) <- with(mydat, paste(AY, DY, sep="-"))

    # # remove CYs before the beginCY
    # if (!is.na(beginCY)){
    #     mydat <- mydat[mydat$CY >= beginCY,]
    # }

    # # relevel CYf incase any levels were removed
    # mydat$CYf <- factor(as.character(mydat$CYf))

    # mydat <- mydat[order(mydat$AY),]

    # mydat <- inner_join(x = mydat, y = Triangle, by = c("AY"))
    # mydat <- mydat[c('AY','DY','CY','AYf','DYf','CYf', 'value','logvalue', 'Exposure')]
    # rownames(mydat) <- paste(mydat$AY,mydat$DY,sep='-')
    # mydat$id = rownames(mydat)
    # mydat <- mydat[order(mydat$AY),]

    # return(mydat)

    # }
    # #########End of tritomatrix Function############################################
    def _tritomatrix(self, beginAY: int = None, beginCY: int = None) -> pd.DataFrame:
        """
        Returns a design matrix that can be used with the logic in Josh Brady's
        R code.

        Parameters
        ----------
        beginAY : int, optional
            The first accident year to include, by default None
            If None, all accident years are included.
        beginCY : int, optional
            The first calendar year to include, by default None
            If None, all calendar years are included.

        Returns
        -------
        pd.DataFrame
            The design matrix.

        Notes
        -----
        This method does not take a "Triangle" data frame as input, but rather
        uses the .GetX() method to get the triangle data. This is because the
        .GetX() method does some additional processing that is needed for this
        method to correctly filter the data.
        """
        # Get the triangle data
        Triangle = self.GetX("train")
        Triangle["AY"] = self.GetAcc("train")
        Triangle["DY"] = self.GetDev("train")
        Triangle["CY"] = self.GetCal("train")
        Triangle["value"] = self.GetY("train")

        # Keep AYs >= beginAY
        if beginAY is not None:
            Triangle = Triangle[Triangle["AY"] >= beginAY]

        # number of accident years
        I = Triangle.shape[0]

        # number of development years + 1, gives column number for last AY
        D1 = Triangle.shape[1] - 1

        initay = self.GetAcc("train").min()  # The first accident year
        curray = self.GetCal("train").max()  # The current year

        # adj for exposure, remove AY and Exposure columns
        # sweep takes the triangle and divides '/' by the exposure vector accross rows
        TriAdj = Triangle.iloc[:, 1:D1].div(Triangle.iloc[:, -1], axis=0)

        D = TriAdj.shape[1]  # number of development year

        TriAdj.columns = list(range(D))  # data is ready as input triangle

        # convert to data frame
        mymatx = pd.DataFrame(
            {
                "AY": np.repeat(np.arange(initay, curray + 1), D),
                "DY": np.tile(np.arange(D), I),
                "value": TriAdj.values.flatten(),
            }
        )

        # If incremental<=0 set NA
        mymatx.loc[mymatx["value"] <= 0, "value"] = np.nan

        # Add dimensions as factors
        mydat = pd.DataFrame(
            {
                "AY": mymatx["AY"],
                "DY": mymatx["DY"],
                "CY": mymatx["AY"] + mymatx["DY"],
                "AYf": mymatx["AY"].astype("category"),
                "DYf": mymatx["DY"].astype("category"),
                "CYf": (mymatx["AY"] + mymatx["DY"]).astype("category"),
                "value": mymatx["value"],
                "logvalue": np.log(mymatx["value"]),
            }
        )

        mydat.index = [f"{x}-{y}" for x, y in zip(mydat["AY"], mydat["DY"])]

        # remove CYs before the beginCY
        if beginCY is not None:
            mydat = mydat[mydat["CY"] >= beginCY]

        # relevel CYf incase any levels were removed
        mydat["CYf"] = mydat["CYf"].cat.remove_unused_categories()

        mydat = mydat.sort_values("AY")

        mydat = mydat.merge(Triangle, on="AY", how="inner")
        mydat = mydat[
            ["AY", "DY", "CY", "AYf", "DYf", "CYf", "value", "logvalue", "Exposure"]
        ]
        mydat.index = [f"{x}-{y}" for x, y in zip(mydat["AY"], mydat["DY"])]
        mydat["id"] = mydat.index
        mydat = mydat.sort_values("AY")

        return mydat

    # #### inc.plot funtion #################################################################################
    # inc.plot <- function(dat, newWindow = TRUE) {
    # # Creats interaction plot of inc payments and log inc payments vs. DY
    # #
    # # Args:
    # #   dat: data frame containing plot data
    # #   newWindow: Choose to have the plot show up in a new window

    # if (newWindow == TRUE) {
    #     x11()  # Create plot in new window
    # }

    # # Set window parameters
    # op <- par(mfrow=c(2,1),oma = c(0, 0, 3, 0))

    # with(dat,
    #     interaction.plot(DY, AY, value,col=1:nlevels(AYf),fixed=1,main="Incremental Payments",legend=F))
    # with(dat,points(1+DY, value, pch=16, cex=0.8))
    # with(dat,
    #     interaction.plot(DY, AY, logvalue,col=1:nlevels(AYf),fixed=1,main="Log Incremental Payments",legend=F))
    # with(dat,points(1+DY, logvalue, pch=16, cex=0.8))
    # par(op)
    # }
    # #### End of inc.plot funtion ###############################################
    def inc_plot(self) -> None:
        """
        Creates interaction plot of inc payments and log inc payments vs. DY

        Returns
        -------
        None.
        """
        # Create subplots: 2 rows
        fig = sp.make_subplots(rows=2, cols=1)

        # Unique levels of AY
        levels = self.GetAcc("train").unique()

        # Plot for each AY level
        for level in levels:
            # Filter for data
            filter = self.GetAcc("train") == level

            # Scatter plot for value
            fig.add_trace(
                go.Scatter(
                    x=self.GetDev("train")[filter],
                    y=self.GetY("train")[filter],
                    mode="lines+markers",
                    name=f"Incremental Payments AY {level}",
                ),
                row=1,
                col=1,
            )
            # Scatter plot for logvalue
            fig.add_trace(
                go.Scatter(
                    x=self.GetDev("train")[filter],
                    y=np.log(self.GetY("train")[filter]),
                    mode="lines+markers",
                    name=f"Log Incremental Payments AY {level}",
                ),
                row=2,
                col=1,
            )

        # Update layout
        fig.update_layout(
            height=600,
            width=800,
            title_text="Incremental Payments and Log Incremental Payments vs. DY",
        )
        fig.update_yaxes(title_text="Value", row=1, col=1)
        fig.update_yaxes(title_text="Log Value", row=2, col=1)

        fig.show()

    # ## 2.Design matrix function ########################################

    # designmatrix <- function(YY,varb) {
    # varb<-as.character(varb)
    # YY<- data.frame(YY)
    # n<- nlevels(as.factor(YY[,1]))     ## number of levels of calandar(payment) year
    # L<- min(YY)                        ## minimum calendar(payment) year
    # S<- max(YY)
    # FF<- apply(YY, 1, function(x) t(as.vector(c(rep(1,x-L),rep(0,n-1-(x-L))))))
    # FF<- t(as.matrix(FF))
    # colnames(FF)<- paste(varb, (L+1):S, sep = "")
    # return(FF)
    # }

    # ## End of Design matrix function## # # # # # # # # # # # # # # # # # # # # #
    def _designmatrix(self) -> None:
        """
        Returns the specific version of the design matrix that is used in the R code.
        """
        X = self.GetX("train")
        X["value"] = self.GetY("train")
        X["AY"] = self.GetAcc("train")
        X["DY"] = self.GetDev("train")
        X["CY"] = self.GetCal("train")
        return X

    # ##### updateTrends ##############################################################
    # updateTrends <- function(resObj,plots = TRUE, customFutureCYTrend = FALSE, customFutureCYStdError = FALSE){
    # # Function takes selected groups definitions and joins appropriate variables to reserve data
    # #
    # # Args
    # #     resObj: which contains the following pertenant members
    # #     plots: after updating the data we fit the model; when polts == TRUE plots are created in fitModel

    # #   browser()
    # ### Initialize variables from reserve object
    # dat <- resObj$dat
    # AYGp <- resObj$AYGp
    # DYGp <- resObj$DYGp
    # CYGp <- resObj$CYGp
    # trendVars <- resObj$trendVars

    # ### Remove current variable definitions
    # # create vector containing each current variable name, created from last process of this funtion
    # groupsToDrop <- unique(trendVars)

    # columnsToRemove = which(names(dat) %in% groupsToDrop)

    # # Remove variables from data frame, check first to make sure there are variables to remove
    # if (length(columnsToRemove) > 0 ) {dat <- dat[-columnsToRemove]}

    # # reset trendVars to NULL; variables will be added to trendVars below
    # trendVars <- NULL

    # ##### (1) Accident Year Trend: ALPHA
    # # Form dataframe contiaing all levels with placeholders for groups
    # alphadm <- (outer(dat$AYf, levels(dat$AYf), `==`)*1)
    # rownames(alphadm)<-rownames(dat)
    # colnames(alphadm) <- paste("alpha",sep="",levels(dat$AYf))

    # # Get unique groups
    # gps = unique(AYGp$gp)

    # # Set placeholder matrix of number of rows in data x number of vars (groups)
    # ALPHA<-matrix(0,ncol=length(gps),nrow=nrow(dat))

    # # for each element of the group we multiply full design matrix against a vector corresponding to AY groupings
    # for (i in 1:length(gps)){

    #     # create placeholder vector corresponding to levels of AYf and set levels corresponding to current group to 1
    #     A<- as.vector(rep(0,nlevels(dat$AYf)))
    #     pos = AYGp[AYGp$gp == gps[i],1]-min(dat$AY)+1
    #     A[pos] = 1
    #     # collopse full design matrix by position group vector
    #     ALPHA[,i]<-alphadm %*% A
    # }

    # colnames(ALPHA)<- paste(gps)
    # rownames(ALPHA)<-rownames(dat)
    # trendVars <- c(trendVars,colnames(ALPHA))

    # ##### (2) Development Year Trend: GAMMA
    # DYM<- dat['DY']
    # # Create full design matrix
    # DYdm<- designmatrix(DYM,"gamma")
    # # Drop 0 level
    # gps = unique(DYGp[DYGp$gp != 0,]$gp)[drop = TRUE]
    # GAMMA<-matrix(0,ncol=length(gps),nrow=nrow(dat))
    # for (i in 1:length(gps)) {
    #     g<- as.vector(rep(0,nlevels(dat$DYf)-1))
    #     pos <- DYGp[DYGp$gp == as.character(gps[i]), 1]
    #     g[pos]<-1
    #     GAMMA[,i]<-DYdm %*% g
    # }
    # #   colnames(GAMMA)<- paste("GAMMA",1:length(gps),sep="")  ## input AY names in a group
    # colnames(GAMMA)<- paste(gps)  ## input AY names in a group
    # rownames(GAMMA)<-rownames(dat)
    # trendVars <- c(trendVars,colnames(GAMMA))

    # ##### (3) Payment Year Trend: IOTA
    # CYM<- dat['CY']

    # # rownames(CYM)<-rownames(dat)
    # CYdm<- designmatrix(CYM,"iota")

    # gps = unique(CYGp[CYGp$gp != 0,]$gp)[drop = TRUE]
    # IOTA<-matrix(0,ncol=length(gps),nrow=nrow(dat))

    # # in case of zero trend check if there is at least one group
    # if (length(gps)>0){
    #     for (i in 1:length(gps)) {
    #     I <- as.vector(rep(0,length(unique(dat$CY))-1))
    #     pos <- CYGp[CYGp$gp == as.character(gps[i]), 1] - min(dat$CY)
    #     I[pos]<-1
    #     IOTA[,i]<-CYdm %*% I
    #     }
    #     colnames(IOTA)<- paste(gps)
    #     rownames(IOTA)<- rownames(dat)
    #     trendVars <- c(trendVars,colnames(IOTA))
    # }

    # dat  <-  cbind(dat,ALPHA,GAMMA,IOTA)
    # rownames(dat) <- dat$id
    # resObj$dat  <-  dat
    # resObj$trendVars <- trendVars

    # # update the AYgpFilters based on the updated AY variable groups

    # AYvars <- unique(AYGp$gp)
    # AYgpFilters <- data.frame(gp = AYvars, filter = rep('none',length(AYvars)))
    # resObj$AYgpFilters <- AYgpFilters
    # resObj <- fitModel(resObj,plots = plots,
    #                   customFutureCYTrend = customFutureCYTrend,
    #                   customFutureCYStdError = customFutureCYStdError,
    #                   UserSelectedModel = ROCKY.settings$selected.model,
    #                   UserSelectedGLMModel = ROCKY.settings$GLM$selected.model)
    # return(resObj)

    # }
    # ##### End of updateTrends function ###########################################
    def _update_trends(
        self,
        plots: bool = True,
        custom_future_CY_trend: bool = False,
        custom_future_CY_std_error: bool = False,
    ):
        # Initialize variables from reserve object
        dat = self.GetX("train")
        AYGp = self.acc_gp
        DYGp = self.dev_gp
        CYGp = self.cal_gp

        # Reset trend_vars to NULL; variables will be added to trend_vars below
        trend_vars = []

        # Get the design matrix and accident year/development year/calendar year/Y values
        X = self.GetX("train")
        acc = self.GetAcc("train")
        cal = self.GetCal("train")

        # Updating alpha, gamma, and iota
        for column in X.columns:
            # if this is an accident period variable
            if "accident_period_" in column:
                # get the group id
                alpha_group = AYGp[AYGp["gp"] == column.split("_")[-1]]

                # get the alpha positions relative to the minimum accident year
                # in the data set
                alpha_positions = alpha_group["gp"].values - min(acc) + 1

                # multiply the design matrix by the alpha positions
                dat[column] = X[column].values * alpha_positions

                # now the alpha positions are the column names of the design matrix

            # Gamma
            if "development_period_" in column:
                gamma_group = DYGp[DYGp["gp"] == column.split("_")[-1]]
                gamma_positions = gamma_group["gp"].values
                dat[column] = X[column].values * gamma_positions

            # Iota
            if "calendar_period_" in column:
                iota_group = CYGp[CYGp["gp"] == column.split("_")[-1]]
                iota_positions = iota_group["gp"].values - min(cal)
                dat[column] = X[column].values * iota_positions

            trend_vars.append(column)

        # update the reserve object
        # res_obj["dat"] = dat
        # res_obj["trendVars"] = trend_vars

        # Update the AYgpFilters based on the updated AY variable groups
        AY_vars = np.unique(AYGp["gp"])
        AY_gp_filters = pd.DataFrame({"gp": AY_vars, "filter": ["none"] * len(AY_vars)})
        self.acc_gp_filter = AY_gp_filters

        res_obj = self._fitModel()

        return res_obj

    def _ProcessVarUBE(self) -> float:
        """
        Implementation of the process variance (unbiased estimator) from Josh Brady's
        original rocky code.

        Returns:
        --------
        procVarUBE: float
            The process variance (unbiased estimator) of the residuals of the model.

        Reference:
        ----------

        From Josh Brady's original rocky code:

        # If the model was fitted on filtered data, then the process variance returned
        # by the fit is not the process variance of the data.
        # This step calculates the unfiltered data total process variance. The sigma squared.
        # Let y = act - fit, w equal the weights vector, and dgf be the degress of freedom.
        # Then the process (vectors calculated elementwise) var = sum(y^2 * w)/dgf
        # Individual process variance = (total process var)/(weight for observation)
        # UBE represent unbiased estimator due to dividing by the degrees of freedom.
        # MLE estimator would be found by dividing by the number of observations used to
        # fit the model.
        procVarUBE <- sum((fitDat$logvalueAct - fitted(model))^2 * fitDat$w)/model$df.residual
        resObj$procVarUBE <- procVarUBE
        """
        y = self.RawResiduals(log=True)
        num = (y**2) * self.GetWeights(kind="train")
        num = num.sum()
        den = self.GetDegreesOfFreedom()
        return num / den if den > 0 else np.nan

    def _ProcessVarMLE(self):
        """
        Implementation of the process variance (maxium likelihood estimator) from Josh Brady's
        original rocky code.

        Returns:
        --------
        procVarMLE: float
            The process variance (maximum likelihood estimator) of the model.

        Reference:
        ----------

        From Josh Brady's original rocky code:

        # If the model was fitted on filtered data, then the process variance returned
        # by the fit is not the process variance of the data.
        # This step calculates the unfiltered data total process variance. The sigma squared.
        # Let y = act - fit, w equal the weights vector, and dgf be the degress of freedom.
        # Then the process (vectors calculated elementwise) var = sum(y^2 * w)/dgf
        # Individual process variance = (total process var)/(weight for observation)
        # UBE represent unbiased estimator due to dividing by the degrees of freedom.
        # MLE estimator would be found by dividing by the number of observations used to
        # fit the model.
        procVarUBE <- sum((fitDat$logvalueAct - fitted(model))^2 * fitDat$w)/model$df.residual
        resObj$procVarUBE <- procVarUBE
        """
        ube = self._ProcessVarUBE()
        n = self.GetN(kind="train")
        return ube / n if n > 0 else np.nan

    def _StandardError(self, process_var_est="ube") -> pd.Series:
        """
        Implementation of the standard error from Josh Brady's original rocky code.

        Parameters
        ----------
        process_var_est : str, optional
            The process variance estimator to use. Must be one of 'ube' or 'mle'.
            The default is 'ube'.

        Returns
        -------
        se : pd.Series

        References
        ----------
        From Josh Brady's code:
        # weight matrix
        W <- diag(fitDat$w) (diagonal matrix whose diagonal is the weights vector)

        # calculate standard errors
        varMat <- (solve(W) - X %*% solve(t(X) %*% W %*% X) %*% t(X))*procVarUBE

        # use abs below to eliminate numbers that are just slightly negative, but
        # should be 0 (due to precision issues)
        se <- sqrt(abs(diag(varMat)))

        """
        # get the weights
        W_vec = self.GetWeights(kind="train")

        # get the diagonal matrix of weights
        W = np.diag(W_vec.values.flatten())

        # get the X matrix (design matrix)
        X = self.GetX(kind="train").values

        # get the process variance
        if process_var_est == "ube":
            V = self._ProcessVarUBE()
        elif process_var_est == "mle":
            V = self._ProcessVarMLE()
        else:
            raise ValueError("process_var_est must be 'ube' or 'mle'")

        # calculate the variance matrix
        varMatrix = (np.linalg.inv(W) - X @ np.linalg.inv(X.T @ W @ X) @ X.T) * V

        # return the standard errors
        se = np.sqrt(np.abs(np.diag(varMatrix)))
        return pd.Series(se, index=self.GetX(kind="train").columns, name="Std Error")

    def _StandardizedResiduals(self) -> pd.Series:
        """
        Implementation of the standardized residuals from Josh Brady's original rocky
        code.

        Parameters
        ----------
        None

        Returns
        -------
        pd.Series
            The standardized residuals.

        References
        ----------

        From Josh Brady's code:
        # Difference between actual (unfiltered) logvalue and fitted
        act_fit <- fitDat$logvalueAct - fitted(model)

        # standardized residuals
        residStd <- act_fit/se
        """
        y = self.GetY(kind="train", log=True)
        yhat = self.GetYhat(kind="train", log=True)
        se = self._StandardError()

        act_fit = y - yhat

        std_resid = act_fit / se

        # return pd.Series
        return pd.Series(
            std_resid, index=self.GetX(kind="train").index, name="Std Residuals"
        )

    def _FitData(self):
        """
        Implementation of the process of building the fit data from Josh Brady's
        original rocky code.

        This method does not return anything, but it does adjust the train_index
        attribute of the model. When .GetX() or .GetY() is called, the train_index
        attribute is used to filter the data.

        Parameters
        ----------
        None

        Returns
        -------
        pd.DataFrame
            The fit data.

        References
        ----------

        From Josh Brady's code:
        # We restrict the fitting data to non NA logvalue. This is done automatically
        # by lm, but we make it clear here and fitDat is used below
        dat <- resObj$dat

        # do non NA logvalue if using loglinear model
        fitDat <- dat[ !is.na(dat$logvalue),]
        """
        datY = self.GetY(kind="train", log=True)

        # get the indices of the non-NaN values
        idx = datY[~datY.isna()].index

        # adjust self.train_index
        self.train_index = idx

    def _lm(self) -> ElasticNet:
        """
        Implementation of the linear model from Josh Brady's original rocky code:
        `model <- lm(modelFormula,data = fitDat,weights = w)`

        Parameters
        ----------
        None

        Returns
        -------
        sklearn.linear_model.ElaticNet
            The linear model.
        """
        # ensure the data have been filtered
        self._FitData()

        # get the X, y, and weights
        X = self.GetX(kind="train")
        y = self.GetY(kind="train", log=True)
        w = self.GetWeights(kind="train")

        # fit the model
        model = ElasticNet(
            alpha=self.alpha,
            l1_ratio=self.l1_ratio,
            max_iter=self.max_iter,
            fit_intercept=False,
            **self.kwargs,
        )

        model.fit(X, y, sample_weight=w)

        # return the model
        return model

    def _CalcHeteroAdj(self) -> pd.Series:
        """
        Implements the `calcWeights` function from Josh Brady's original rocky code.

        Parameters
        ----------

        Returns
        -------

        References
        ----------

        From Josh Brady's code:
        calcWeights <- function(resObj){
        # The function uses the selected groups to update weights (resObj$DYw)
        # The updated weights = current weights * inverse of variance of std residuals
        # in each group
        # Returns resObj with updated resObj$DYw
        # Note that the weights in the reserve data (resObj$dat$w) are not updated
        # running fitModel(resObj,updateWeights = TRUE) will update the weights in
        # $dat and $model

        dat = resObj$dat
        model = resObj$model
        DYwGp <- resObj$DYwGp
        names(DYwGp)[2] <- "gp"
        DYw <- resObj$DYw

        # join weight groups to data frame
        dat$gp <- NULL
        dat <- inner_join(dat,DYwGp,by = 'DY')
        rownames(dat) = dat$id


        #   names(dat)[ncol(dat)] <- 'wGp'


        # For calculating standardized residuals we need to restrict to data used to fit the model.
        fitDat <- dat[!is.na(dat$logvalue),]

        # calculate variance of residuals over each group then format to data frame
        resGps <- fitDat[,c('id','DY','gp','residStd')]

        # subract mean for each DY
        DYmean <- resGps %>% group_by(DY) %>% summarize( DYmu = mean(residStd))
        resGps <- inner_join(resGps,DYmean,by = 'DY')
        resGps$residStd <- resGps$residStd - resGps$DYmu
        wGpVar <- resGps %>% group_by(gp) %>% summarise(var = popVar(residStd))


        # Check if there were errors in calculating varaince. If so, exit.
        if (any(is.na(wGpVar)) | any(wGpVar == 0) == TRUE){
            stop("Variance of group either 0 or NA")
        }

        # the adjustment weight is the inverse of the variance
        wGpVar$wAdj <- wGpVar$var^(-1)

        # rescale
        wGpVar$wAdj <- wGpVar$wAdj/wGpVar$wAdj[1]

        # join weight adj to DY on the DYwGp. Arrange to ensure DY are lined up
        DYwAdj <- inner_join(DYwGp,wGpVar,by = 'gp')
        DYwAdj <- arrange(DYwAdj, DY)
        # Update weights in DYW
        DYw$w <- DYw$w * DYwAdj$wAdj

        #note that the weights in dat have not been updated, running fitModel with updateWeights = TRUE updates the model weights
        # update resObj
        resObj$dat <- dat
        resObj$DYw <- DYw
        return(resObj)
        }


        """
        # Initialize variables from res_obj
        dat = self.GetX("train")
        DYwGp = pd.concat([self.GetDev('train'), self.GetHeteroGp().loc[self.GetIdx('train')]], axis=1)
        DYwGp.rename(columns={DYwGp.columns[0]: "gp"}, inplace=True)
        DYw = self.GetWeights("train")

        # join weight groups to data frame
        dat = DYwGp.join(dat)

        # For calculating standardized residuals we need to restrict to data used
        # to fit the model (this is already done by the GetX method)
        fit_dat = dat.copy()
        fit_dat["residStd"] = self._StandardizedResiduals()

        # calculate variance of residuals over each group then format to data frame
        res_gps = fit_dat[["DY", "gp", "residStd"]]

        # subtract mean for each DY
        DYmean = res_gps.groupby("DY")["residStd"].mean()
        res_gps = res_gps.merge(DYmean, on="DY", suffixes=("", "_mean"))
        res_gps["residStd"] -= res_gps["residStd_mean"]

        # calculate variance of residuals over each group then format to data frame
        wGpVar = res_gps.groupby("gp")["residStd"].var(ddof=0).reset_index()

        # Check if there were errors in calculating variance. If so, exit.
        if wGpVar["residStd"].isna().any() or (wGpVar["residStd"] == 0).any():
            raise Exception("Variance of group either 0 or NA")

        # the adjustment weight is the inverse of the variance
        wGpVar["wAdj"] = wGpVar["residStd"] ** (-1)

        # rescale
        wGpVar["wAdj"] /= wGpVar["wAdj"].iloc[0]

        # join weight adj to DY on the DYwGp. Arrange to ensure DY are lined up
        DYwAdj = DYwGp.merge(wGpVar, on="gp").sort_values(by="DY")

        # Update weights in DYW
        DYw["w"] *= DYwAdj["wAdj"]

        # update development year weights
        h_gps = self.GetHeteroGp()
        h_gps["w"] = DYw["w"]
        self.SetHeteroGp(h_gps)

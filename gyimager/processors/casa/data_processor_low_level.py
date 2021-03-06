from ..data_processor_low_level_base import DataProcessorLowLevelBase
import itertools
import os.path as path
import numpy
import casaimwrap
from ...algorithms import constants
import pyrap.tables
import imaging_weight

class DataProcessorLowLevel(DataProcessorLowLevelBase):
    def __init__(self, measurement, options):
        self._measurement = measurement
        self._ms = pyrap.tables.table(measurement, readonly = False)
        self._ms = self._ms.query("ANTENNA1 != ANTENNA2 && OBSERVATION_ID ==" \
            " 0 && FIELD_ID == 0 && DATA_DESC_ID == 0")

#        assert(options["weight_algorithm"] == WeightAlgorithm.NATURAL)

	# INI: 'outcol' is defined in degridder. If called from degridder, this is a value read from the command line.
	if options.has_key("outcol"):
          self._data_column = options["outcol"]
	else:
	  self._data_column = "CORRECTED_DATA"

        self._modeldata_column = "MODEL_DATA"

        self._coordinates = None
        self._shape = None
        self._response_available = False

        # Defaults from awimager.
        parms = {}
        parms["wmax"] = options["w_max"]
        parms["mueller.grid"] = numpy.ones((4, 4), dtype=bool)
        parms["mueller.degrid"] = numpy.ones((4, 4), dtype=bool)
        parms["verbose"] = 0                # 1, 2 for more output
        parms["maxsupport"] = 1024
        parms["oversample"] = 8
        parms["output.imagename"] = options["image"]
        parms["UseLIG"] = False             # linear interpolation
        parms["UseEJones"] = True
        parms["ApplyElement"] = True
        parms["PBCut"] = 5e-2
#        parms["StepApplyElement"] = 0       # if 0 don't apply element beam
        parms["StepApplyElement"] = 1000       # if 0 don't apply element beam
#        parms["TWElement"] = 0.02
        parms["PredictFT"] = False
        parms["PsfImage"] = ""
        parms["UseMasksDegrid"] = True
        parms["RowBlock"] = 10000000
        parms["doPSF"] = False
        parms["applyIonosphere"] = False
        parms["applyBeam"] = True
        parms["splitbeam"] = True
        parms["padding"] = options["padding"]
        # will be determined by LofarFTMachine
        parms["wplanes"] = 0

        parms["ApplyBeamCode"] = 0
#        parms["ApplyBeamCode"] = 1
#        parms["ApplyBeamCode"] = 3
        parms["UVmin"] = 0
        parms["UVmax"] = 100000
        parms["MakeDirtyCorr"] = False

        parms["timewindow"] = 300
        parms["TWElement"] = 20
        parms["UseWSplit"] = True
        parms["SingleGridMode"] = True
        parms["SpheSupport"] = 15
        parms["t0"] = -1
        parms["t1"] = -1
        parms["ChanBlockSize"] = 0
        parms["FindNWplanes"] = True
        
        parms["gridding.ATerm.name"] = options["gridding.ATerm.name"]
        parms["ATermPython.module"] = options["ATermPython.module"]
        parms["ATermPython.class"] = options["ATermPython.class"]

        weightoptionnames = ["weighttype", "rmode", "noise", "robustness"]
        weightoptions = dict( (key, value) for (key,value) in options.iteritems() if key in weightoptionnames)
        self.imw = imaging_weight.ImagingWeight(**weightoptions)

        self._context = casaimwrap.CASAContext()
        casaimwrap.init(self._context, self._measurement, parms)

    def capabilities(self):
        return {}

    def phase_reference(self):
        field = pyrap.tables.table(path.join(self._measurement, "FIELD"))
        # Assumed to be in J2000 for now.
        assert(field.getcolkeyword("PHASE_DIR", "MEASINFO")["Ref"] == "J2000")
        return field.getcell("PHASE_DIR", 0)[0]

    def channel_frequency(self):
        spw = pyrap.tables.table(path.join(self._measurement, \
            "SPECTRAL_WINDOW"))
        return spw.getcell("CHAN_FREQ", 0)

    def channel_width(self):
        spw = pyrap.tables.table(path.join(self._measurement, \
            "SPECTRAL_WINDOW"))
        return spw.getcell("CHAN_WIDTH", 0)

    def maximum_baseline_length(self):
        return numpy.max(numpy.sqrt(numpy.sum(numpy.square( \
            self._ms.getcol("UVW")), 1)))

    def density(self, coordinates, shape):
        increment = coordinates.get_increment()
        freqs = self.channel_frequency()
        f = freqs/constants.speed_of_light

        density_shape = shape[2:]
        density_increment = increment[2]

        uorig = int(density_shape[1]/2)
        vorig = int(density_shape[0]/2)

        density = numpy.zeros(density_shape)
        uscale = density_shape[1]*density_increment[1]
        vscale = density_shape[0]*density_increment[0]
        uvw = self._ms.getcol("UVW")
        weight = self._ms.getcol("WEIGHT_SPECTRUM")
        for i in range(len(self._ms)):
          u1 = uvw[i,0]*uscale
          v1 = uvw[i,1]*vscale
          for j in range(len(f)):
              u = int(u1*f[j])
              v = int(v1*f[j])
              if abs(u)<uorig and abs(v)<vorig :
                  w = sum(weight[i, j,:])
                  density[vorig+v,uorig+u] += w
                  density[vorig-v,uorig-u] += w
        return density

    def set_density(self, density, coordinates) :
        self.imw.set_density(density, coordinates)

    def response(self, coordinates, shape):
        self._update_image_configuration(coordinates, shape)
        assert self._response_available, "Response not available"
        return casaimwrap.average_response(self._context)

    def point_spread_function(self, coordinates, shape, as_grid):
        assert(not as_grid)
        self._update_image_configuration(coordinates, shape)

        args = {}
        args["ANTENNA1"] = self._ms.getcol("ANTENNA1")
        args["ANTENNA2"] = self._ms.getcol("ANTENNA2")
        args["UVW"] = self._ms.getcol("UVW")
        args["TIME"] = self._ms.getcol("TIME")
        args["TIME_CENTROID"] = self._ms.getcol("TIME_CENTROID")
        args["FLAG_ROW"] = self._ms.getcol("FLAG_ROW")
        args["FLAG"] = self._ms.getcol("FLAG")
        #args["IMAGING_WEIGHT"] = self.imw.imaging_weight(args["UVW"], \
            #self.channel_frequency(), args["FLAG"], self._ms.getcol("WEIGHT_SPECTRUM"))
        args["IMAGING_WEIGHT_CUBE"] = numpy.ones(args["FLAG"].shape, dtype=numpy.float32)
        args["DATA"] = numpy.ones(args["FLAG"].shape, dtype=numpy.complex64)

        casaimwrap.begin_grid(self._context, shape, coordinates.dict(), \
            True, args)
        result = casaimwrap.end_grid(self._context, False)
        return (result["image"], result["weight"])

    def grid(self, coordinates, shape, as_grid):
        assert(not as_grid)
        self._update_image_configuration(coordinates, shape)

        args = {}
        args["ANTENNA1"] = self._ms.getcol("ANTENNA1")
        args["ANTENNA2"] = self._ms.getcol("ANTENNA2")
        args["UVW"] = self._ms.getcol("UVW")
        args["TIME"] = self._ms.getcol("TIME")
        args["TIME_CENTROID"] = self._ms.getcol("TIME_CENTROID")
        args["FLAG_ROW"] = self._ms.getcol("FLAG_ROW")
        args["FLAG"] = self._ms.getcol("FLAG")
        args["IMAGING_WEIGHT_CUBE"] = numpy.ones(args["FLAG"].shape, dtype=numpy.float32)
        args["DATA"] = self._ms.getcol(self._data_column)

	# INI: Modified grid in casaimwrap to separate begin_grid, grid and end_grid
        '''casaimwrap.begin_grid(self._context, shape, coordinates.dict(), \
            False, args)
        result = casaimwrap.end_grid(self._context, False)'''

        casaimwrap.begin_grid(self._context, shape, coordinates.dict(), \
            False)
        casaimwrap.grid(self._context, \
            args)
        result = casaimwrap.end_grid(self._context, False) # INI: why is this False? Insert proper options here

        self._response_available = True
        return (result["image"], result["weight"])

    def grid_chunk(self, coordinates, shape, as_grid, chunksize):
        assert(not as_grid)
        self._update_image_configuration(coordinates, shape)

        casaimwrap.begin_grid(self._context, shape, coordinates.dict(), \
            False)

        # INI: looping through chunks of data
        nrows = self._ms.nrows()
        lastchunksize = nrows % chunksize
        if lastchunksize > 0:
            nchunks = nrows / chunksize + 1
        else:
            nchunks = nrows / chunksize

        print 'nrows, chunksize, lastchunksize: ', nrows, chunksize, lastchunksize

        for chunk in numpy.arange(nchunks):
                start = chunk * chunksize
                if chunk == nchunks-1 and lastchunksize > 0:
                        nrow = lastchunksize
                else:
                        nrow = chunksize

	        args = {}
        	args["ANTENNA1"] = self._ms.getcol("ANTENNA1",start,nrow)
	        args["ANTENNA2"] = self._ms.getcol("ANTENNA2",start,nrow)
        	args["UVW"] = self._ms.getcol("UVW",start,nrow)
	        args["TIME"] = self._ms.getcol("TIME",start,nrow)
        	args["TIME_CENTROID"] = self._ms.getcol("TIME_CENTROID",start,nrow)
	        args["FLAG_ROW"] = self._ms.getcol("FLAG_ROW",start,nrow)
        	args["FLAG"] = self._ms.getcol("FLAG",start,nrow)
	        args["IMAGING_WEIGHT_CUBE"] = numpy.ones(args["FLAG"].shape, dtype=numpy.float32)
        	args["DATA"] = self._ms.getcol(self._data_column,start,nrow)

	        casaimwrap.grid(self._context, \
        	    args)

        result = casaimwrap.end_grid(self._context, False) # INI: why is this False? Insert proper options here

	print "Result is ------------------: ", result

        self._response_available = True
        return (result["image"], result["weight"])

    def degrid(self, coordinates, model, as_grid):
        assert(not as_grid)
        self._update_image_configuration(coordinates, model.shape)

        args = {}
        args["ANTENNA1"] = self._ms.getcol("ANTENNA1")
        args["ANTENNA2"] = self._ms.getcol("ANTENNA2")
        args["UVW"] = self._ms.getcol("UVW")
        args["TIME"] = self._ms.getcol("TIME")
        args["TIME_CENTROID"] = self._ms.getcol("TIME_CENTROID")
        args["FLAG_ROW"] = self._ms.getcol("FLAG_ROW")
        args["FLAG"] = self._ms.getcol("FLAG")
        args["IMAGING_WEIGHT_CUBE"] = numpy.ones(args["FLAG"].shape, dtype=numpy.float32)

        casaimwrap.begin_degrid(self._context, \
            coordinates.dict(), model)
          
        result = casaimwrap.degrid(self._context, \
            args)
          
        casaimwrap.end_degrid(self._context)
        self._response_available = True
	# INI: uncommenting the line below so that the result is written to the MS.
        self._ms.putcol(self._data_column, result["data"])

    def degrid_chunk(self, coordinates, model, as_grid, chunksize):
        assert(not as_grid)
        self._update_image_configuration(coordinates, model.shape)

        casaimwrap.begin_degrid(self._context, \
            coordinates.dict(), model)

	# INI: looping through chunks of data
	nrows = self._ms.nrows()
	lastchunksize = nrows % chunksize
	if lastchunksize > 0:
	    nchunks = nrows / chunksize + 1
	else:
	    nchunks = nrows / chunksize

	print 'nrows, chunksize, lastchunksize: ', nrows, chunksize, lastchunksize

	for chunk in numpy.arange(nchunks):
		start = chunk * chunksize
		if chunk == nchunks-1 and lastchunksize > 0:
			nrow = lastchunksize
		else:
			nrow = chunksize

	        args = {}
	        args["ANTENNA1"] = self._ms.getcol("ANTENNA1",start,nrow)
	        args["ANTENNA2"] = self._ms.getcol("ANTENNA2",start,nrow)
	        args["UVW"] = self._ms.getcol("UVW",start,nrow)
	        args["TIME"] = self._ms.getcol("TIME",start,nrow)
	        args["TIME_CENTROID"] = self._ms.getcol("TIME_CENTROID",start,nrow)
	        args["FLAG_ROW"] = self._ms.getcol("FLAG_ROW",start,nrow)
	        args["FLAG"] = self._ms.getcol("FLAG",start,nrow)
	        args["IMAGING_WEIGHT_CUBE"] = numpy.ones(args["FLAG"].shape, dtype=numpy.float32)
     
        	result = casaimwrap.degrid(self._context, \
	            args)
	        self._ms.putcol(self._data_column, result["data"], start, nrow)
          
        casaimwrap.end_degrid(self._context)

        self._response_available = True

    def residual(self, coordinates, model, as_grid):
        assert(not as_grid)
        self._update_image_configuration(coordinates, model.shape)

        # Degrid model.
        args = {}
        args["ANTENNA1"] = self._ms.getcol("ANTENNA1")
        args["ANTENNA2"] = self._ms.getcol("ANTENNA2")
        args["UVW"] = self._ms.getcol("UVW")
        args["TIME"] = self._ms.getcol("TIME")
        args["TIME_CENTROID"] = self._ms.getcol("TIME_CENTROID")
        args["FLAG_ROW"] = self._ms.getcol("FLAG_ROW")
        args["FLAG"] = self._ms.getcol("FLAG")
        args["IMAGING_WEIGHT_CUBE"] = numpy.ones(args["FLAG"].shape, dtype=numpy.float32)

        result = casaimwrap.begin_degrid(self._context, \
            coordinates.dict(), model, args)
        casaimwrap.end_degrid(self._context)

        # Compute residual.
        residual = self._ms.getcol(self._data_column) - result["data"]

        # Grid residual.
        args = {}
        args["ANTENNA1"] = self._ms.getcol("ANTENNA1")
        args["ANTENNA2"] = self._ms.getcol("ANTENNA2")
        args["UVW"] = self._ms.getcol("UVW")
        args["TIME"] = self._ms.getcol("TIME")
        args["TIME_CENTROID"] = self._ms.getcol("TIME_CENTROID")
        args["FLAG_ROW"] = self._ms.getcol("FLAG_ROW")
        args["FLAG"] = self._ms.getcol("FLAG")
        args["IMAGING_WEIGHT_CUBE"] = numpy.ones(args["FLAG"].shape, dtype=numpy.float32)
        args["DATA"] = residual

        casaimwrap.begin_grid(self._context, model.shape, \
            coordinates.dict(), False, args)
        result = casaimwrap.end_grid(self._context, False)
        self._response_available = True

        return (result["image"], result["weight"])

    def _update_image_configuration(self, coordinates, shape):
        # Comparing coordinate systems is tricky!
        #
        # A straightforward coordinates1 != coordinates2 yields True if
        # coordinates1 and coordinates2 are different objects, even if they
        # represent the same coordinate system.
        #
        # Here we compare the string representation of the coordinate systems.
        # A better solution would be to overload the __cmp__() method of the
        # coordinatesystem class, with a proper comparison, including a
        # tolerance for comparing floating point numbers.
        #
        if str(self._coordinates) != str(coordinates) or self._shape != shape:
            self._coordinates = coordinates
            self._shape = shape
            self._response_available = False

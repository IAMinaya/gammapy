# Licensed under a 3-clause BSD style license - see LICENSE.rst
from __future__ import print_function, division
import numpy as np
import matplotlib.pyplot as plt
from astropy import log
from astropy.io import fits
from astropy.units import Quantity
from astropy.coordinates import Angle, SkyCoord
from astropy.table import Table
from ..extern.validator import validate_physical_type
from ..utils.array import array_stats_str
from scipy.interpolate import LinearNDInterpolator, RectBivariateSpline


__all__ = ['abramowski_effective_area', 'TableEffectiveArea', 'OffsetDependentTableEffectiveArea']



def abramowski_effective_area(energy, instrument='HESS'):
    """Simple IACT effective area parametrizations from Abramowski et al. (2010).

    TODO: give formula

    Parametrizations of the effective areas of Cherenkov telescopes
    taken from Appendix B of http://adsabs.harvard.edu/abs/2010MNRAS.402.1342A .

    Parameters
    ----------
    energy : `~astropy.units.Quantity`
        Energy
    instrument : {'HESS', 'HESS2', 'CTA'}
        Instrument name

    Returns
    -------
    effective_area : `~astropy.units.Quantity`
        Effective area in cm^2
    """
    # Put the parameters g in a dictionary.
    # Units: g1 (cm^2), g2 (), g3 (MeV)
    # Note that whereas in the paper the parameter index is 1-based,
    # here it is 0-based
    pars = {'HESS': [6.85e9, 0.0891, 5e5],
            'HESS2': [2.05e9, 0.0891, 1e5],
            'CTA': [1.71e11, 0.0891, 1e5]}

    if not isinstance(energy, Quantity):
        raise ValueError("energy must be a Quantity object.")

    energy = energy.to('MeV').value

    if not instrument in pars.keys():
        ss = 'Unknown instrument: {0}\n'.format(instrument)
        ss += 'Valid instruments: HESS, HESS2, CTA'
        raise ValueError(ss)

    g1 = pars[instrument][0]
    g2 = pars[instrument][1]
    g3 = -pars[instrument][2]
    value = g1 * energy ** (-g2) * np.exp(g3 / energy)
    return Quantity(value, 'cm^2')


class TableEffectiveArea(object):
    """
    Effective area table class.

    Not interpolation is used.

    Parameters
    ----------
    energy_lo : `~astropy.units.Quantity`
        Lower energy boundary of the energy bin.
    energy_hi : `~astropy.units.Quantity`
        Upper energy boundary of the energy bin.
    effective_area : `~astropy.units.Quantity`
        Effective area at the given energy bins.
    energy_thresh_lo : `~astropy.units.Quantity`
        Lower save energy threshold of the psf.
    energy_thresh_hi : `~astropy.units.Quantity`
        Upper save energy threshold of the psf.

    Examples
    --------
    Plot effective area vs. energy:

     .. plot::
        :include-source:

        import matplotlib.pyplot as plt
        from gammapy.irf import TableEffectiveArea
        from gammapy.datasets import load_arf_fits_table
        arf = TableEffectiveArea.from_fits(load_arf_fits_table())
        arf.plot_area_vs_energy(show_save_energy=False)
        plt.show()
    """
    def __init__(self, energy_lo, energy_hi, effective_area,
                 energy_thresh_lo=Quantity(0.1, 'TeV'),
                 energy_thresh_hi=Quantity(100, 'TeV')):

        # Validate input
        validate_physical_type('energy_lo', energy_lo, 'energy')
        validate_physical_type('energy_hi', energy_hi, 'energy')
        validate_physical_type('effective_area', effective_area, 'area')
        validate_physical_type('energy_thresh_lo', energy_thresh_lo, 'energy')
        validate_physical_type('energy_thresh_hi', energy_thresh_hi, 'energy')

        # Set attributes
        self.energy_hi = energy_hi.to('TeV')
        self.energy_lo = energy_lo.to('TeV')
        self.effective_area = effective_area.to('m^2')
        self.energy_thresh_lo = energy_thresh_lo.to('TeV')
        self.energy_thresh_hi = energy_thresh_hi.to('TeV')

    def to_fits(self, header=None, **kwargs):
        """
        Convert ARF to FITS HDU list format.

        Parameters
        ----------
        header : `~astropy.io.fits.header.Header`
            Header to be written in the fits file.

        Returns
        -------
        hdu_list : `~astropy.io.fits.HDUList`
            ARF in HDU list format.

        Notes
        -----
        For more info on the ARF FITS file format see:
        http://heasarc.gsfc.nasa.gov/docs/heasarc/caldb/docs/summary/cal_gen_92_002_summary.html

        Recommended units for ARF tables are keV and cm^2, but TeV and m^2 are chosen here
        as the more natural units for IACTs
        """
        hdu = fits.new_table(
            [fits.Column(name='ENERG_LO',
                          format='1E',
                          array=self.energy_lo,
                          unit='TeV'),
             fits.Column(name='ENERG_HI',
                          format='1E',
                          array=self.energy_hi,
                          unit='TeV'),
             fits.Column(name='SPECRESP',
                          format='1E',
                          array=self.effective_area,
                          unit='m^2')
             ]
            )

        if header is None:
            from ..datasets import load_arf_fits_table
            header = load_arf_fits_table()[1].header

        if header == 'pyfact':
            header = hdu.header

            # Write FITS extension header
            header['EXTNAME'] = 'SPECRESP', 'Name of this binary table extension'
            header['TELESCOP'] = 'DUMMY', 'Mission/satellite name'
            header['INSTRUME'] = 'DUMMY', 'Instrument/detector'
            header['FILTER'] = 'NONE', 'Filter information'
            header['HDUCLASS'] = 'OGIP', 'Organisation devising file format'
            header['HDUCLAS1'] = 'RESPONSE', 'File relates to response of instrument'
            header['HDUCLAS2'] = 'SPECRESP', 'Effective area data is stored'
            header['HDUVERS '] = '1.1.0', 'Version of file format'

            header['PHAFILE'] = ('', 'PHA file for which ARF was produced')

            # Obsolete ARF headers, included for the benefit of old software
            header['ARFVERSN'] = '1992a', 'Obsolete'
            header['HDUVERS1'] = '1.0.0', 'Obsolete'
            header['HDUVERS2'] = '1.1.0', 'Obsolete'

        for key, value in kwargs.items():
            header[key] = value

        header['LO_THRES'] = self.energy_thresh_lo.value
        header['HI_THRES'] = self.energy_thresh_hi.value

        prim_hdu = fits.PrimaryHDU()
        hdu.header = header
        hdu.add_checksum()
        hdu.add_datasum()
        return fits.HDUList([prim_hdu, hdu])

    def write(self, filename, *args, **kwargs):
        """Write ARF to FITS file.

        Calls `~astropy.io.fits.HDUList.writeto`, forwarding all arguments.
        """
        self.to_fits().writeto(filename, *args, **kwargs)

    @staticmethod
    def read(filename):
        """Read FITS format ARF file.

        Parameters
        ----------
        filename : str
            File name

        Returns
        -------
        parf : `EnergyDependentARF`
            ARF object.
        """
        hdu_list = fits.open(filename)
        return TableEffectiveArea.from_fits(hdu_list)

    @staticmethod
    def from_fits(hdu_list):
        """
        Create EnergyDependentARF from HDU list.

        Parameters
        ----------
        hdu_list : `~astropy.io.fits.HDUList`
            HDU list with ``SPECRESP`` extensions.

        Returns
        -------
        arf : `EnergyDependentARF`
            ARF object.

        Notes
        -----
        For more info on the ARF FITS file format see:
        http://heasarc.gsfc.nasa.gov/docs/heasarc/caldb/docs/summary/cal_gen_92_002_summary.html

        Recommended units for ARF tables are keV and cm^2, but TeV and m^2 are chosen here
        as the more natural units for IACTs.
        """
        energy_lo = Quantity(hdu_list['SPECRESP'].data['ENERG_LO'], 'TeV')
        energy_hi = Quantity(hdu_list['SPECRESP'].data['ENERG_HI'], 'TeV')
        effective_area = Quantity(hdu_list['SPECRESP'].data['SPECRESP'], 'm^2')
        try:
            energy_thresh_lo = Quantity(hdu_list['SPECRESP'].header['LO_THRES'], 'TeV')
            energy_thresh_hi = Quantity(hdu_list['SPECRESP'].header['HI_THRES'], 'TeV')
            return TableEffectiveArea(energy_lo, energy_hi, effective_area,
                                      energy_thresh_lo, energy_thresh_hi)
        except KeyError:
            log.warn('No safe energy thresholds found. Setting to default')
            return TableEffectiveArea(energy_lo, energy_hi, effective_area)

    def effective_area_at_energy(self, energy):
        """
        Get effective area for given energy.

        Not interpolation is used.

        Parameters
        ----------
        energy : `~astropy.units.Quantity`
            Energy where to return effective area.

        Returns
        -------
        effective_area : `~astropy.units.Quantity`
            Effective area at given energy.
        """
        if not isinstance(energy, Quantity):
            raise ValueError("energy must be a Quantity object.")

        # TODO: Use some kind of interpolation here
        i = np.argmin(np.abs(self.energy_hi - energy))
        return self.effective_area[i]

    def info(self, energies=Quantity([1, 10], 'TeV')):
        """
        Print some ARF info.

        Parameters
        ----------
        energies : `~astropy.units.Quantity`
            Energies for which to print effective areas.
        """
        ss = "\nSummary ARF info\n"
        ss += "----------------\n"
        # Summarise data members
        ss += array_stats_str(self.energy_lo, 'Energy lo')
        ss += array_stats_str(self.energy_hi, 'Energy hi')
        ss += array_stats_str(self.effective_area.to('m^2'), 'Effective area')
        ss += 'Safe energy threshold lo: {0:6.3f}\n'.format(self.energy_thresh_lo)
        ss += 'Safe energy threshold hi: {0:6.3f}\n'.format(self.energy_thresh_hi)

        for energy in energies:
            eff_area = self.effective_area_at_energy(energy)
            ss += ("Effective area at E = {0:4.1f}: {1:10.0f}\n".format(energy, eff_area))
        return ss

    def plot_area_vs_energy(self, filename=None, show_save_energy=True):
        """
        Plot effective area vs. energy.
        """
        import matplotlib.pyplot as plt

        energy_hi = self.energy_hi.value
        effective_area = self.effective_area.value
        plt.plot(energy_hi, effective_area)
        if show_save_energy:
            plt.vlines(self.energy_thresh_hi.value, 1E3, 1E7, 'k', linestyles='--')
            plt.text(self.energy_thresh_hi.value - 1, 3E6,
                     'Safe energy threshold: {0:3.2f}'.format(self.energy_thresh_hi),
                     ha='right')
            plt.vlines(self.energy_thresh_lo.value, 1E3, 1E7, 'k', linestyles='--')
            plt.text(self.energy_thresh_lo.value + 0.1, 3E3,
                     'Safe energy threshold: {0:3.2f}'.format(self.energy_thresh_lo))
        plt.xlim(0.1, 100)
        plt.ylim(1E3, 1E7)
        plt.loglog()
        plt.xlabel('Energy [TeV]')
        plt.ylabel('Effective Area [m^2]')
        if filename is not None:
            plt.savefig(filename)
            log.info('Wrote {0}'.format(filename))


class OffsetDependentTableEffectiveArea(object):
    """Offset-dependent radially-symmetric table effective area (``GCTAAeff2D FITS`` format).

    The table is  read by interpolated by triangulating the input data with Qhull (http://www.qhull.org/R42).
    This behaviour can be change to 2D spline interpolation with set_interpolation_method.

    Parameters
    ----------
    energ_lo : `~astropy.units.Quantity`
        Lower energy bin edges vector 
    energ_hi : `~astropy.units.Quantity`
        Upper energy bin edges vector
    offset_lo : `~astropy.coordonates.Angle`
        Lower offset bin edges vector 
    offset_hi : `~astropy.coordonates.Angle`
        Upper offset bin edges  vector
    eff_area : `~astropy.units.Quantity`
        Effective area vector (true energy)
    eff_area_reco : `~astropy.units.Quantity`
        Effective area vector (reconstructed energy)

    Examples
    --------
    Get effective area vs. energy for a given offset and energy binning:

     .. plot::
        :include-source:

        import numpy as np
        from astropy.coordinates import Angle
        from astropy.units import Quantity
        from gammapy.irf import OffsetDependentTableEffectiveArea
        from gammapy.datasets import load_aeff2D_fits_table

        aeff2D = OffsetDependentTableEffectiveArea.from_fits(load_aeff2D_fits_table())
        offset  = Angle( 0.6 , 'degree')
        energies = Quantity(np.logspace(0,1,60), 'TeV')
        eff_area = aeff2D.eval_at_offset(offset,energies)
        
    """
    def __init__(self, energ_lo, energ_hi, offset_lo, offset_hi, eff_area, eff_area_reco):
        if not isinstance(energ_lo, Quantity) or not isinstance(energ_hi, Quantity):
            raise ValueError("Energies must be Quantity objects.")
        if not isinstance(offset_lo, Angle) or not isinstance(offset_hi, Angle):
            raise ValueError("Offsets must be Angle objects.")
        if not isinstance(eff_area, Quantity) or not isinstance(eff_area_reco, Quantity):
            raise ValueError("Effective areas must be Quantity objects.")

        self.energ_lo      = energ_lo.to('TeV')
        self.energ_hi      = energ_hi.to('TeV')
        self.offset_lo     = offset_lo.to('degree')
        self.offset_hi     = offset_hi.to('degree')
        self.eff_area      = eff_area.to('m^2')
        self.eff_area_reco = eff_area_reco.to('m^2')
        
        self.offset = (offset_hi+offset_lo)/2  #actually offset_hi = offset_lo
        self.energy = np.sqrt(energ_lo*energ_hi)

        self._prepare_linear_interpolator()
        self._prepare_spline_interpolator()

        self._interpolation_method='linear'  #set to linear interpolation by default

    @staticmethod
    def from_fits(hdu_list):
        """Create OffsetDependentTableEffectiveArea from ``GCTAAeff2D`` format HDU list.

        Parameters
        ----------
        hdu_list : `~astropy.io.fits.HDUList`
            HDU list with ``EFFECTIVE AREA`` extension.

        Returns
        -------
        eff_area : `OffsetDependentTableEffectiveArea`
            Offset dependent Effective Area object.
        """
        energ_lo = Quantity(hdu_list['EFFECTIVE AREA'].data['ENERG_LO'][0,:], 'TeV')
        energ_hi = Quantity(hdu_list['EFFECTIVE AREA'].data['ENERG_HI'][0,:], 'TeV')
        offset_lo = Angle(hdu_list['EFFECTIVE AREA'].data['THETA_LO'][0,:], 'degree')
        offset_hi = Angle(hdu_list['EFFECTIVE AREA'].data['THETA_HI'][0,:], 'degree')
        eff_area = Quantity(hdu_list['EFFECTIVE AREA'].data['EFFAREA'][0,:,:], 'm^2')
        eff_area_reco = Quantity(hdu_list['EFFECTIVE AREA'].data['EFFAREA_RECO'][0,:,:], 'm^2')

        return OffsetDependentTableEffectiveArea(energ_lo, energ_hi, offset_lo, offset_hi, eff_area, eff_area_reco)


    @staticmethod
    def read(filename):
        """Read FITS format Effective Area file (``GCTAAeff2D`` output).

        Parameters
        ----------
        filename : str
            File name

        Returns
        -------
        eff_area : `OffsetDependentTableEffectiveArea`
            Offset dependent Effective Area object.
    
        """
        hdu_list = fits.open(filename)
        return OffsetDependentTableEffectiveArea.from_fits(hdu_list)

    
    def __call__(self,offset, energy):
        """ Executes evaluate function 
        """
        return self.evaluate(offset,energy)
        
        
        
    def evaluate(self,offset, energy):
        """
        Evalute Effective Area for a given energy and offset 
        The Interpolation method is defined by self._interpolation_method

        Parameters
        ----------
        offset : Angle
            offset 

        energy : Quantity
            energy


        Returns
        -------
        eff_area : `~astropy.units.Quantity`
            Effective Area 

        """
        if not isinstance(energy, Quantity) or not isinstance(offset, Angle):
            raise ValueError("Energies (Offset) must be a Quantity (Angle) object.")

        offset = offset.to('degree')
        energy = energy.to('TeV')

        if(self._interpolation_method=='linear'):
            val =  self._linear(offset.value,np.log10(energy.value))
        elif (self._interpolation_method=='spline'):
            val =  self._spline(offset.value,np.log10(energy.value)).squeeze()
        else:
            raise NotImplementedError("An unavailable interpolation method was set by hand.")

        return Quantity(val,self.eff_area.unit)
           
        
    def eval_at_offset(self,offset,energies=[]):
        """
        Return Effective Area histogram for a given offset 
        An optional energy array can provide the binning of the histogram (usefull for spectral fitting).
        If none is given, the energies values in the Lookup table are used

        Uses memebr function 'evaluate'
        
        Parameters
        ----------
        offset : Angle
            offset 

        Returns
        -------
        eff_area : `~astropy.units.Quantity`
            Effective Area histogram

        """
        if not isinstance(offset, Angle):
            raise ValueError("Offset must be an Angle object.")
        
        enarray=self.energy if energies==[] else energies
        
        areahist = self.evaluate(offset,enarray)
        return areahist

    def eval_at_energy(self,energy,offsets=[]):
        """
        Return Effective Area histogram for a given energy
        Uses member function 'evaluate'
        
        Parameters
        ----------
        energy : Quantity
            energy

        Returns
        -------
        eff_area : `~astropy.units.Quantity`
            Effective Area histogram

        #TODO: support 1D or 2D arrays of offsets
        #NOTE: flatten and reshape

        """
        if not isinstance(energy, Quantity):
            raise ValueError("Energies must be a Quantity object.")

        offarray=self.offset if offsets==[] else offsets

        areahist = self.evaluate(offarray,energy)
        return areahist


    def plot_at_offset(self,offset,energies=[]):
        """
        Plot Effective Area histogram for a given offset 
        Uses memebr function 'eval_at_offset'
        """
        areahist = self.eval_at_offset(offset,energies)

        enarray=self.energy if energies==[] else energies  #code duplication find better solution

        plt.plot(enarray,areahist.value, 'ro')
        plt.xlabel('Energy ({0})'.format(self.energy.unit))
        plt.ylabel('Effective Area ({0})'.format(areahist.unit))

    def plot_at_energy(self,energy):
        """
        Plot Effective Area histogram for a given energy
        Uses member function 'eval_at_energy'

        #TODO: support 1D or 2D arrays of offsets
        """
        areahist = self.eval_at_energy(energy)
        plt.plot(self.offset.value,areahist.value, 'bo')
        plt.xlabel('Offset ({0})'.format(self.offset.unit))
        plt.ylabel('Effective Area ({0})'.format(areahist.unit))
        
    
    def set_interpolation_method(self,method):
        """
        Choose method used for interpolating the lookup table
        Available methods
        - linear
        - spline
        """

        if not method in ['linear','spline']:
            raise NotImplementedError("The method you require is not implemented.")

        self._interpolation_method = method
    

    def _prepare_linear_interpolator(self):
        """
        Could be generalized for non-radial symmetric input files (N>2)
        The interpolant is constructed by triangulating the input data with Qhull (http://www.qhull.org/R42) and on each triangle performing linear barycentric interpolation.
        """
        x = self.offset.value
        y = np.log10(self.energy.value)
        coord = [(xx, yy) for xx in x for yy in y]
        
        self._linear = LinearNDInterpolator(coord,self.eff_area.value.flatten())


    def _prepare_spline_interpolator(self):
        """
        Bivariate spline approximation over a rectangular mesh.
        Only works for radial symmetric input files (N=2)
        """
        x = self.offset.value
        y = np.log10(self.energy.value)
        
        self._spline = RectBivariateSpline(x,y,self.eff_area.value)


#unused helper functions (remove?)

    def _get_1d_eff_area_values(self, offset_index, reco = False):
        """Get 1-dim Effective Area array.

        Parameters
        ----------
        offset_index : int
            offset index

        Returns
        -------
        eff_area : `~astropy.units.Quantity`
            Effective Area array 
        """
        eff_area = self.eff_area[0,offset_index,].copy()
        return eff_area


    def _offset_index(self, offset):
        """Find index for a given offset (always rounded up)
        """
        return np.searchsorted(self.offset[0,:].value, offset)  

    def _energy_index(self, energy):
        """Find index for a given energy (always rounded up)
        """
        return np.searchsorted(self.energy[0,:].value, energy)  


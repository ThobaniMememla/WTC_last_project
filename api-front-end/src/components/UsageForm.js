import React, { useState } from 'react';
import axios from 'axios';

const UsageForm = () => {
    const [msisdn, setMsisdn] = useState('');
    const [startTime, setStartTime] = useState('');
    const [endTime, setEndTime] = useState('');
    const [usageData, setUsageData] = useState(null);
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        try {
            const response = await axios.get('http://localhost:8000/data_usage', {
                params: {
                    msisdn,
                    start_time: startTime,
                    end_time: endTime,
                },
            });
            setUsageData(response.data);
            setError(null);
        } catch (err) {
            setError('Error fetching data');
            setUsageData(null);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="container mx-auto p-4">
            <h1 className="text-2xl font-bold mb-4">Usage Data Form</h1>
            <form onSubmit={handleSubmit} className="mb-4">
                <div className="mb-4">
                    <label className="block text-gray-700">MSISDN:</label>
                    <input
                        type="text"
                        value={msisdn}
                        onChange={(e) => setMsisdn(e.target.value)}
                        required
                        className="w-full px-3 py-2 border rounded"
                    />
                </div>
                <div className="mb-4">
                    <label className="block text-gray-700">Start Time (YYYYMMDDHHMMSS):</label>
                    <input
                        type="text"
                        value={startTime}
                        onChange={(e) => setStartTime(e.target.value)}
                        required
                        className="w-full px-3 py-2 border rounded"
                    />
                </div>
                <div className="mb-4">
                    <label className="block text-gray-700">End Time (YYYYMMDDHHMMSS):</label>
                    <input
                        type="text"
                        value={endTime}
                        onChange={(e) => setEndTime(e.target.value)}
                        required
                        className="w-full px-3 py-2 border rounded"
                    />
                </div>
                <button
                    type="submit"
                    className="bg-blue-500 text-white px-4 py-2 rounded"
                    disabled={loading}
                >
                    {loading ? 'Fetching...' : 'Fetch Usage Data'}
                </button>
            </form>
            {error && <p className="text-red-500">{error}</p>}
            {usageData && (
                <div>
                    <h2 className="text-xl font-bold mb-4">Usage Data</h2>
                    <div className="overflow-x-auto">
                        <table className="min-w-full bg-white border border-gray-300">
                            <thead>
                                <tr>
                                    <th className="border border-gray-300 px-4 py-2">Category</th>
                                    <th className="border border-gray-300 px-4 py-2">Usage Type</th>
                                    <th className="border border-gray-300 px-4 py-2">Total</th>
                                    <th className="border border-gray-300 px-4 py-2">Measure</th>
                                    <th className="border border-gray-300 px-4 py-2">Start Time</th>
                                </tr>
                            </thead>
                            <tbody>
                                {usageData.usage.map((record, index) => (
                                    <tr key={index}>
                                        <td className="border border-gray-300 px-4 py-2">{record.category}</td>
                                        <td className="border border-gray-300 px-4 py-2">{record.usage_type}</td>
                                        <td className="border border-gray-300 px-4 py-2">{record.total}</td>
                                        <td className="border border-gray-300 px-4 py-2">{record.measure}</td>
                                        <td className="border border-gray-300 px-4 py-2">{record.start_time}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
};

export default UsageForm;